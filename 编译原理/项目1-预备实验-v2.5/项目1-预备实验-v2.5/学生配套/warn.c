#include <stdio.h>
int missing_return(void) { }
int main(void) {
    int unused = 0;
    int x;
    int y = 0;
    if (y = 5) printf("y=%d\n", y);
    printf("%d\n", "wrong type");
    return x;
}
