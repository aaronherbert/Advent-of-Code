#include <stdio.h>
int main(void) {
    long long x, a = 0, b = 0;
    while (scanf("%lld", &x) == 1) { a += x; b += x * x; }
    printf("%lld\n%lld\n", a, b);
    return 0;
}
