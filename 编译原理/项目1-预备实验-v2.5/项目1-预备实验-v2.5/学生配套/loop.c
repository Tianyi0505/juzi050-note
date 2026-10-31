#include <stdio.h>
#include <time.h>
#define N 10000000LL
int main(void) {
    long long sum = 0;
    clock_t start = clock();
    for (long long i = 0; i < N; i++)
        sum += i * 2 + 1;
    clock_t end = clock();
    if (start == (clock_t)-1 || end == (clock_t)-1) {
        fputs("CPU time unavailable\n", stderr);
        return 1;
    }
    printf("sum = %lld\n", sum);
    printf("loop CPU time = %.6f s\n",
           (double)(end - start) / CLOCKS_PER_SEC);
    return 0;
}
