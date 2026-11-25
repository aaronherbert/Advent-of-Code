import sys
n = [int(x) for x in sys.stdin.read().split()]
print(sum(n))
print(sum(x * x for x in n))
