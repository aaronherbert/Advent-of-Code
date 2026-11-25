a=0; b=0
while read -r x; do
  [ -z "$x" ] && continue
  a=$((a + x)); b=$((b + x * x))
done
echo "$a"
echo "$b"
