#include <iostream>
int main() {
    long long x, a = 0, b = 0;
    while (std::cin >> x) { a += x; b += x * x; }
    std::cout << a << "\n" << b << "\n";
}
