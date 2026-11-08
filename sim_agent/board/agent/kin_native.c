/* Model-exported transforms; same damped least-squares and limits as kin.py. */
#include <math.h>
#include <string.h>
static const double home[7]={0,0,0,-1.57079,0,1.57079,-.7853};
static double clamp(double x,double a,double b){return fmax(a,fmin(b,x));}
static void eye(double*r){memset(r,0,9*sizeof(double));r[0]=r[4]=r[8]=1;}
static void mv(const double*r,const double*v,double*out){for(int i=0;i<3;i++)out[i]=r[3*i]*v[0]+r[3*i+1]*v[1]+r[3*i+2]*v[2];}
static void mm(const double*a,const double*b,double*c){double v[9]={0};for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++)v[3*i+j]+=a[3*i+k]*b[3*k+j];memcpy(c,v,sizeof(v));}
static void rot(const double*a,double angle,double*r){double c=cos(angle),s=sin(angle);for(int i=0;i<3;i++)for(int j=0;j<3;j++)r[3*i+j]=(i==j?c:0)+(1-c)*a[i]*a[j];r[1]-=s*a[2];r[2]+=s*a[1];r[3]+=s*a[2];r[5]-=s*a[0];r[6]-=s*a[1];r[7]+=s*a[0];}
static void fk(const double*f,int n,const double*tcp,const double*q,double*p,double*r,double*j){
 double axes[21]={0},origins[21]={0};memset(p,0,3*sizeof(double));eye(r);
 for(int b=0;b<n;b++){
  const double*v=f+b*20;double off[3];mv(r,v,off);for(int k=0;k<3;k++)p[k]+=off[k];mm(r,v+3,r);int index=(int)v[19];
  if(index>=0){double anchor[3],rr[9];mv(r,v+12,anchor);for(int k=0;k<3;k++)origins[3*index+k]=p[k]+anchor[k];mv(r,v+15,axes+3*index);rot(v+15,q[index]-v[18],rr);mm(r,rr,r);mv(r,v+12,anchor);for(int k=0;k<3;k++)p[k]=origins[3*index+k]-anchor[k];}
 }
 double off[3];mv(r,tcp,off);for(int k=0;k<3;k++)p[k]+=off[k];mm(r,tcp+3,r);
 if(j)for(int i=0;i<7;i++){double*d=axes+3*i,v[3];for(int k=0;k<3;k++)v[k]=p[k]-origins[3*i+k];j[i]=d[1]*v[2]-d[2]*v[1];j[7+i]=d[2]*v[0]-d[0]*v[2];j[14+i]=d[0]*v[1]-d[1]*v[0];for(int k=0;k<3;k++)j[(3+k)*7+i]=d[k];}
}
static void re(const double*t,const double*r,double*e){
 double d[9]={0};for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++)d[3*i+j]+=t[3*i+k]*r[3*j+k];
 double angle=acos(clamp((d[0]+d[4]+d[8]-1)/2,-1,1));e[0]=d[7]-d[5];e[1]=d[2]-d[6];e[2]=d[3]-d[1];
 if(angle<1e-7){for(int i=0;i<3;i++)e[i]*=.5;return;}
 if(3.141592653589793-angle<1e-5){int m=d[4]>d[0]?1:0;if(d[8]>d[4*m])m=2;double a[3]={0};a[m]=sqrt(fmax(0,(d[4*m]+1)/2));for(int i=0;i<3;i++)if(i!=m)a[i]=(d[3*m+i]+d[3*i+m])/(4*fmax(a[m],1e-10));double dot=0;for(int i=0;i<3;i++)dot+=a[i]*e[i];for(int i=0;i<3;i++)e[i]=a[i]*angle*(dot<0?-1:1);return;}
 for(int i=0;i<3;i++)e[i]*=angle/(2*sin(angle));
}
static double error(const double*target,const double*tr,const double*p,const double*r,double*e){double rot_error[3];re(tr,r,rot_error);double score=0;for(int i=0;i<3;i++){e[i]=target[i]-p[i];e[i+3]=rot_error[i]*.4;}for(int i=0;i<6;i++)score+=e[i]*e[i];return sqrt(score);}
static int solve(double a[6][8]){
 for(int k=0;k<6;k++){int pivot=k;for(int i=k+1;i<6;i++)if(fabs(a[i][k])>fabs(a[pivot][k]))pivot=i;if(fabs(a[pivot][k])<1e-14)return 0;for(int j=k;j<8;j++){double v=a[k][j];a[k][j]=a[pivot][j];a[pivot][j]=v;}double v=a[k][k];for(int j=k;j<8;j++)a[k][j]/=v;for(int i=0;i<6;i++)if(i!=k){v=a[i][k];for(int j=k;j<8;j++)a[i][j]-=v*a[k][j];}}
 return 1;
}
int rv_ik(const double*f,int n,const double*tcp,const double*limits,const double*target,const double*tr,const double*seed,double*q){
 for(int i=0;i<7;i++)q[i]=clamp(seed[i],limits[2*i],limits[2*i+1]);
 for(int iter=0;iter<200;iter++){
  double p[3],r[9],j[42],e[6];fk(f,n,tcp,q,p,r,j);double score=error(target,tr,p,r,e),pe=0,re2=0;for(int i=0;i<3;i++){pe+=e[i]*e[i];re2+=e[i+3]*e[i+3]/.16;}
  if(pe<1e-6 && re2<.0003046174197867086)return iter+1;
  for(int i=21;i<42;i++)j[i]*=.4;
  double bias[7],a[6][8]={{0}};for(int i=0;i<7;i++)bias[i]=.015*(home[i]-q[i]);
  for(int i=0;i<6;i++){for(int k=0;k<6;k++){for(int h=0;h<7;h++)a[i][k]+=j[i*7+h]*j[k*7+h];if(i==k)a[i][k]+=.0001;}a[i][6]=e[i];for(int h=0;h<7;h++)a[i][7]+=j[i*7+h]*bias[h];}
  if(!solve(a))return -2;
  double dq[7],task[7]={0},maximum=0;for(int i=0;i<7;i++){dq[i]=bias[i];for(int k=0;k<6;k++){task[i]+=j[k*7+i]*a[k][6];dq[i]+=j[k*7+i]*(a[k][6]-a[k][7]);}maximum=fmax(maximum,fabs(dq[i]));}
  double factor=fmin(1,.18/fmax(1e-12,maximum));int accepted=0;
  for(double scale=1;scale>=.0625;scale*=.5){double candidate[7],pp[3],rr[9],ee[6];for(int i=0;i<7;i++)candidate[i]=clamp(q[i]+scale*factor*dq[i],limits[2*i]+1e-5,limits[2*i+1]-1e-5);fk(f,n,tcp,candidate,pp,rr,0);if(error(target,tr,pp,rr,ee)<score){memcpy(q,candidate,sizeof(candidate));accepted=1;break;}}
  if(!accepted)for(int i=0;i<7;i++)q[i]=clamp(q[i]+.25*task[i],limits[2*i]+1e-5,limits[2*i+1]-1e-5);
 }
 return -1;
}
