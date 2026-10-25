#include <stdio.h>
#define GREETING "Hello, Compiler!"
int add(int a, int b) { return a + b; }
int main(void) {
    int x = 2, y = 3;
    printf("%s %d + %d = %d\n", GREETING, x, y, add(x, y));
    return 0;
}
