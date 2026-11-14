#include "encoder_under_test.c"
#include <assert.h>
static int spin_us;
static _Atomic uint64_t done;
static _Atomic unsigned errors;
static volatile uint64_t sink;
int vka_gp_active;
int vka_nan_on(void){return 0;}
uint64_t vka_host_fp(const char*who){(void)who;return 0;}
void vka_perf_thread(int nice){(void)nice;}
int test_env(const char*k,int d){if(!strcmp(k,"DM_VK_ENC"))return 1;if(!strcmp(k,"DM_VK_ENC_SPIN_US"))return spin_us;if(!strcmp(k,"DM_VK_ENC_BATCH"))return 4096;return d;}
typedef struct{uint64_t seq,x,y,z;} payload;
static void consume(const void*arg){const payload*p=arg;uint64_t seq=atomic_fetch_add(&done,1);if(p->seq!=seq||p->x!=(seq^0x1234)||p->y!=~seq||p->z!=seq*17)errors++;volatile uint64_t x=p->x;for(int i=0;i<24;i++)x=x*1664525u+1013904223u;sink=x;}
static uint64_t cpu_ns(clockid_t id){struct timespec t;assert(!clock_gettime(id,&t));return(uint64_t)t.tv_sec*1000000000ull+t.tv_nsec;}
int main(int argc,char**argv){
 spin_us=argc>1?atoi(argv[1]):200;
 vka_enc_install();vka_enc_start((VkCommandBuffer)(uintptr_t)1);payload p={0,0x1234,UINT64_MAX,0};assert(vka_enc_call(consume,&p,sizeof p));vka_enc_sync();vka_enc_stop();assert(g_cpu_clock_ok);
 uint64_t seq=1,cpu0=cpu_ns(g_cpu_clock),prod0=cpu_ns(CLOCK_THREAD_CPUTIME_ID),wall0=mono_ns();
 for(int part=0;part<80;part++){
  vka_enc_start((VkCommandBuffer)(uintptr_t)(part+1));
  for(int batch=0;batch<50;batch++){
   for(int i=0;i<64;i++,seq++){p=(payload){seq,seq^0x1234,~seq,seq*17};assert(vka_enc_call(consume,&p,sizeof p));memset(&p,0xee,sizeof p);}
   uint64_t until=mono_ns()+50000;while(mono_ns()<until)__asm__ volatile("":::"memory");
  }
  vka_enc_stop();
 }
 uint64_t wall=mono_ns()-wall0,prod=cpu_ns(CLOCK_THREAD_CPUTIME_ID)-prod0,cpu=cpu_ns(g_cpu_clock)-cpu0;
 assert(!errors&&done==seq);printf("encoder idle spin%d:256000 commands exact; wall %.3f ms, producer CPU %.3f ms, encoder CPU %.3f ms (host ring workload only)\n",spin_us,wall/1e6,prod/1e6,cpu/1e6);
 return 0;
}
