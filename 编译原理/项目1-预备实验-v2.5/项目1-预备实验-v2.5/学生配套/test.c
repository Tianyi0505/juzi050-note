#include <stdio.h>
int main(void) {
    int x = 40;
    x += 2;
#ifdef DEBUG
    printf("[DEBUG] x = %d\n", x);
#endif
    printf("answer = %d\n", x);
    return 0;
}
