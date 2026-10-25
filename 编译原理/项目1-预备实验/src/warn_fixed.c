#include <stdio.h>

int missing_return(void) { return 0; }

int main(void) {
    int x = 0;
    int y = 0;
    if (y == 5) printf("y=%d\n", y);
    printf("%d\n", 42);
    (void)x;
    return 0;
}
