/* Largest 4-connected component of a caller-owned uint8 mask. */
#include <stdlib.h>
#include <stdint.h>
int rv_centroid(uint8_t *mask,int width,int height,double *out){
 if(width<=0 || height<=0 || width>640 || height>480)return -1;
 int size=width*height,*queue=malloc((size_t)size*sizeof(int));if(!queue)return -1;
 int best=0;double bx=0,by=0;
 for(int first=0;first<size;first++)if(mask[first]){
  int head=0,tail=1;queue[0]=first;mask[first]=0;double sx=0,sy=0;
  while(head<tail){int p=queue[head++],x=p%width,y=p/width;sx+=x;sy+=y;
   int next[4]={x?p-1:-1,x+1<width?p+1:-1,y?p-width:-1,y+1<height?p+width:-1};
   for(int k=0;k<4;k++){int n=next[k];if(n>=0 && mask[n]){mask[n]=0;queue[tail++]=n;}}
  }
  if(tail>best){best=tail;bx=sx;by=sy;}
 }
 free(queue);if(best<12)return 0;out[0]=bx/best;out[1]=by/best;out[2]=best;return 1;
}
