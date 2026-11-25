use std::io::Read;
fn main() {
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s).unwrap();
    let (mut a, mut b) = (0i64, 0i64);
    for t in s.split_whitespace() { let x: i64 = t.parse().unwrap(); a += x; b += x * x; }
    println!("{}\n{}", a, b);
}
