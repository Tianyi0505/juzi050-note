#include <stdio.h>
extern int add(int, int);
int main(void) {
    printf("3 + 5 = %d\n", add(3, 5));
    return 0;
}
