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
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
static void on_signal(int sig) { (void)sig; stopping=1; }
static const double lo[7]={-2.8973,-1.7628,-2.8973,-3.0718,-2.8973,-0.0175,-2.8973};
static const double hi[7]={2.8973,1.7628,2.8973,-0.0698,2.8973,3.7525,2.8973};
typedef struct { unsigned long long n,lost,interval_n; double proc_sum,proc_max,dt_sum,dt_sq,dt_max; } stats;
static stats total;
static pthread_mutex_t stats_lock=PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t finished;
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
    int cpu=-1,sine=0;
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--sine")) sine=1;
        else if(!strcmp(argv[i],"--cpu") && i+1<argc) { cpu=atoi(argv[++i]); if(cpu<0 || cpu>=CPU_SETSIZE) return 2; }
        else { fprintf(stderr,"usage: rt_ctl [--sine] [--cpu N]\n"); return 2; }
    }
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal);
    int fd=socket(AF_INET,SOCK_DGRAM,0); if(fd<0) {perror("socket");return 1;}
    struct sockaddr_in local={.sin_family=AF_INET,.sin_port=htons(15001),.sin_addr={.s_addr=htonl(INADDR_ANY)}};
    if(bind(fd,(struct sockaddr*)&local,sizeof(local))) {perror("bind");return 1;}
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
        if(have && !(state.flags&2) && (delta==0 || delta>=0x80000000U))continue;
        if(!have) {memcpy(center,state.q,sizeof(center));first=received;have=1;}
        unsigned long long lost=(previous && !(state.flags&2) && delta>1)?delta-1:0;
        double dt=previous?received-previous:0;previous=received;last=state.seq;
        cmd.ack=state.seq;cmd.mode=(sine && received-first>=2 && !stopping)?1:0;
        for(int i=0;i<7;i++) {
            double target=cmd.mode?center[i]:state.q[i];
            if(cmd.mode && (i==0 || i==3))target+=.3*sin(2*3.141592653589793*(received-first-2)/4);
            cmd.q_des[i]=fmax(lo[i],fmin(hi[i],target));
        }
        cmd.gripper_des=cmd.mode?(((int)((received-first)/4)%2)?0:.08):fmax(0,fmin(.08,state.gripper));
        if(sendto(fd,&cmd,sizeof(cmd),0,(struct sockaddr*)&peer,plen)!=(ssize_t)sizeof(cmd)){perror("sendto");break;}
        cmd.seq++;
        double processing=now_s()-received;
        pthread_mutex_lock(&stats_lock);
        total.n++;total.lost+=lost;total.proc_sum+=processing;total.proc_max=fmax(total.proc_max,processing);
        if(dt>0){total.interval_n++;total.dt_sum+=dt;total.dt_sq+=dt*dt;total.dt_max=fmax(total.dt_max,dt);}
        pthread_mutex_unlock(&stats_lock);
    }
    finished=1; close(fd); pthread_join(log_thread,NULL); munlockall();return 0;
}
