package main

import "fmt"

func main() {
	var x, a, b int64
	for {
		if _, err := fmt.Scan(&x); err != nil {
			break
		}
		a += x
		b += x * x
	}
	fmt.Println(a)
	fmt.Println(b)
}
