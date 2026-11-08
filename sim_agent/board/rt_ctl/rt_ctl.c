#define _GNU_SOURCE
#include "protocol.h"
#include <arpa/inet.h>
#include <errno.h>
#include <math.h>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static const char *owned_socket;
static void remove_owned_socket(void) { if(owned_socket) unlink(owned_socket); }
static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
static void on_signal(int sig) { (void)sig; stopping=1; }
static const double lo[7]={-2.8973,-1.7628,-2.8973,-3.0718,-2.8973,-0.0175,-2.8973};
static const double hi[7]={2.8973,1.7628,2.8973,-0.0698,2.8973,3.7525,2.8973};
typedef struct { unsigned long long n,lost,interval_n; double proc_sum,proc_max,dt_sum,dt_sq,dt_max; } stats;
static stats total;
static pthread_mutex_t stats_lock=PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t finished;
typedef struct __attribute__((packed)) { char magic[4]; uint32_t op; double goal[7], grip, duration; } segment_request;
typedef struct __attribute__((packed)) { char magic[4]; uint32_t status, active, generation; double q[7], q_des[7], grip, grip_des; } segment_reply;
_Static_assert(sizeof(segment_request)==80, "segment request");
_Static_assert(sizeof(segment_reply)==144, "segment reply");
static double start_q[7], goal_q[7], desired[7], start_grip, goal_grip, desired_grip;
static double segment_start, segment_duration;
static int segment_exists, segment_active;
static uint32_t generation;
static void interpolate(double now) {
    if (!segment_exists) return;
    double u=fmax(0,fmin(1,(now-segment_start)/segment_duration));
    double a=u*u*u*(10+u*(-15+6*u));
    for(int i=0;i<7;i++) desired[i]=start_q[i]+a*(goal_q[i]-start_q[i]);
    desired_grip=start_grip+u*(goal_grip-start_grip);
    segment_active=u<1;
}
static void local_requests(int fd, int have, rv_state *state, double now) {
    struct sockaddr_un from; socklen_t len=sizeof(from);
    segment_request request; segment_reply reply;
    /* Bound the nonblocking work per control tick. */
    for(int tries=0;tries<4;tries++) {
        unsigned char raw[81];
        ssize_t n=recvfrom(fd,raw,sizeof(raw),MSG_DONTWAIT,(struct sockaddr*)&from,&len);
        if(n<0) break;
        memset(&reply,0,sizeof(reply)); memcpy(reply.magic,"RVR1",4);
        if(n!=sizeof(request)) reply.status=1;
        else {
            memcpy(&request,raw,sizeof(request));
            int valid=!memcmp(request.magic,"RVT1",4) && request.op>=1 && request.op<=3;
            if(request.op==1) {
                valid=valid && isfinite(request.duration) && request.duration>=.5 && request.duration<=120;
                valid=valid && isfinite(request.grip) && request.grip>=0 && request.grip<=.08;
                for(int i=0;i<7;i++) valid=valid && isfinite(request.goal[i]) && request.goal[i]>=lo[i] && request.goal[i]<=hi[i];
            }
            if(!valid) reply.status=1;
            else if(!have) reply.status=2;
            else if(request.op==3) {segment_exists=segment_active=0;generation++;}
            else if(request.op==1) {
                interpolate(now);
                if(!segment_exists) {memcpy(desired,state->q,sizeof(desired));desired_grip=state->gripper;}
                memcpy(start_q,desired,sizeof(start_q));memcpy(goal_q,request.goal,sizeof(goal_q));
                start_grip=desired_grip;goal_grip=request.grip;segment_start=now;segment_duration=request.duration;
                segment_exists=segment_active=1;generation++;
            }
        }
        reply.active=segment_active;reply.generation=generation;
        if(have) {memcpy(reply.q,state->q,sizeof(reply.q));memcpy(reply.q_des,desired,sizeof(reply.q_des));reply.grip=state->gripper;reply.grip_des=desired_grip;}
        sendto(fd,&reply,sizeof(reply),MSG_DONTWAIT,(struct sockaddr*)&from,len);
        len=sizeof(from);
    }
}
static void *reporter(void *arg) {
    (void)arg;
    do {
        struct timespec pause={1,0}; nanosleep(&pause,NULL);
        pthread_mutex_lock(&stats_lock); stats s=total; pthread_mutex_unlock(&stats_lock);
        double mean=s.interval_n?s.dt_sum/s.interval_n:0;
        printf("{\"rx\":%llu,\"lost\":%llu,\"processing_us_mean\":%.3f,\"processing_us_max\":%.3f,\"interval_ms_mean\":%.6f,\"interval_ms_max\":%.6f,\"interval_ms_std\":%.6f}\n",
            s.n,s.lost,s.n?s.proc_sum/s.n*1e6:0,s.proc_max*1e6,mean*1e3,s.dt_max*1e3,
            sqrt(fmax(0,s.interval_n?s.dt_sq/s.interval_n-mean*mean:0))*1e3);
        fflush(stdout);
    } while(!finished);
    return NULL;
}
int main(int argc,char **argv) {
    int cpu=-1,sine=0; const char *socket_path="/tmp/rt_ctl.sock";
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--sine")) sine=1;
        else if(!strcmp(argv[i],"--cpu") && i+1<argc) { cpu=atoi(argv[++i]); if(cpu<0 || cpu>=CPU_SETSIZE) return 2; }
        else if(!strcmp(argv[i],"--socket") && i+1<argc) socket_path=argv[++i];
        else { fprintf(stderr,"usage: rt_ctl [--sine] [--cpu N] [--socket PATH]\n"); return 2; }
    }
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal);
    int fd=socket(AF_INET,SOCK_DGRAM,0); if(fd<0) {perror("socket");return 1;}
    struct sockaddr_in local={.sin_family=AF_INET,.sin_port=htons(15001),.sin_addr={.s_addr=htonl(INADDR_ANY)}};
    if(bind(fd,(struct sockaddr*)&local,sizeof(local))) {perror("bind");return 1;}
    int local_fd=socket(AF_UNIX,SOCK_DGRAM|SOCK_NONBLOCK,0);
    struct sockaddr_un address={.sun_family=AF_UNIX};
    if(strlen(socket_path)>=sizeof(address.sun_path)) return 2;
    strcpy(address.sun_path,socket_path);
    /* Refuse an existing endpoint: never unlink another controller's socket. */
    if(local_fd<0 || bind(local_fd,(struct sockaddr*)&address,sizeof(address))) {perror("Unix bind");return 1;}
    owned_socket=socket_path;atexit(remove_owned_socket);
    /* Non-RT reporting thread prevents a slow terminal from blocking UDP replies. */
    pthread_t log_thread;
    if(pthread_create(&log_thread,NULL,reporter,NULL)) {fputs("reporter failed\n",stderr);return 1;}
    if(cpu>=0) {cpu_set_t set;CPU_ZERO(&set);CPU_SET(cpu,&set);if(sched_setaffinity(0,sizeof(set),&set)){perror("affinity");return 1;}}
    if(mlockall(MCL_CURRENT|MCL_FUTURE)) {perror("mlockall");return 1;}
    struct sched_param param={.sched_priority=80};
    if(sched_setscheduler(0,SCHED_FIFO,&param)) {perror("SCHED_FIFO");return 1;}
    printf("SCHED_FIFO=80 mlockall=ok cpu=%d sine=%d\n",cpu,sine);fflush(stdout);
    rv_state state; rv_command cmd; memset(&cmd,0,sizeof(cmd));memcpy(cmd.magic,"RVC1",4);
    double first=0,previous=0,stop_deadline=0,center[7]; uint32_t last=0;int have=0;
    struct sockaddr_in peer; socklen_t plen=sizeof(peer);
    while(1) {
        double tick=now_s();
        interpolate(tick);
        local_requests(local_fd,have,&state,tick);
        if(stopping && !stop_deadline) stop_deadline=tick+.5;
        if(stop_deadline && tick>=stop_deadline) break;
        struct pollfd pfd={.fd=fd,.events=POLLIN};
        int ready=poll(&pfd,1,10);if(ready<0){if(errno==EINTR)continue;perror("poll");break;}if(!ready)continue;
        unsigned char packet[145];
        ssize_t n=recvfrom(fd,packet,sizeof(packet),0,(struct sockaddr*)&peer,&plen);
        double received=now_s(); if(n!=(ssize_t)sizeof(state))continue;
        memcpy(&state,packet,sizeof(state));if(memcmp(state.magic,"RVS1",4))continue;
        int valid=isfinite(state.sim_time)&&isfinite(state.gripper);
        for(int i=0;i<7;i++)valid=valid&&isfinite(state.q[i])&&isfinite(state.dq[i]);
        if(!valid)continue;
        uint32_t delta=state.seq-last;
        if(have && state.seq==last && !(state.flags&2))continue;
        if(have && (state.seq<last || (state.flags&2))) {
            pthread_mutex_lock(&stats_lock);memset(&total,0,sizeof(total));pthread_mutex_unlock(&stats_lock);
            previous=0;segment_exists=segment_active=0;have=0;generation++;
        }
        if(!have) {memcpy(center,state.q,sizeof(center));first=received;have=1;}
        unsigned long long lost=(previous && !(state.flags&2) && delta>1)?delta-1:0;
        double dt=previous?received-previous:0;previous=received;last=state.seq;
        interpolate(received);
        if(!segment_exists) {memcpy(desired,state.q,sizeof(desired));desired_grip=state.gripper;}
        cmd.ack=state.seq;cmd.mode=(!stopping && (segment_exists || (sine && received-first>=2)))?1:0;
        for(int i=0;i<7;i++) {
            double target=segment_exists?desired[i]:(cmd.mode?center[i]:state.q[i]);
            if(cmd.mode && sine && !segment_exists && (i==0 || i==3))target+=.3*sin(2*3.141592653589793*(received-first-2)/4);
            cmd.q_des[i]=fmax(lo[i],fmin(hi[i],target));
        }
        cmd.gripper_des=segment_exists?desired_grip:cmd.mode?(((int)((received-first)/4)%2)?0:.08):fmax(0,fmin(.08,state.gripper));
        if(sendto(fd,&cmd,sizeof(cmd),0,(struct sockaddr*)&peer,plen)!=(ssize_t)sizeof(cmd)){perror("sendto");break;}
        cmd.seq++;
        double processing=now_s()-received;
        pthread_mutex_lock(&stats_lock);
        total.n++;total.lost+=lost;total.proc_sum+=processing;total.proc_max=fmax(total.proc_max,processing);
        if(dt>0){total.interval_n++;total.dt_sum+=dt;total.dt_sq+=dt*dt;total.dt_max=fmax(total.dt_max,dt);}
        pthread_mutex_unlock(&stats_lock);
    }
    finished=1; close(fd);close(local_fd); pthread_join(log_thread,NULL); munlockall();return 0;
}
