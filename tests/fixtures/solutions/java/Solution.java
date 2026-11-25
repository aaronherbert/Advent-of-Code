import java.util.Scanner;

public class Solution {
    public static void main(String[] args) {
        Scanner in = new Scanner(System.in);
        long a = 0, b = 0;
        while (in.hasNextLong()) { long x = in.nextLong(); a += x; b += x * x; }
        System.out.println(a);
        System.out.println(b);
    }
}
