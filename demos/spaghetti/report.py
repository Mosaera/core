import sys

# script-kiddie sales report -- global state, copy-pasted parsing, magic numbers,
# no functions worth the name, NO TESTS, NO pytest config. runs, but nothing
# validates behaviour. (this tangle is deliberate: the demo is about the WEAK
# oracle on a testless repo, not about clean code.)

data = []
total = 0
count = 0

lines = open(sys.argv[1]).read().split("\n") if len(sys.argv) > 1 else []
for l in lines:
    if l.strip() == "":
        continue
    parts = l.split(",")
    # region
    r = parts[0]
    # amount
    a = parts[1]
    try:
        a = float(a)
    except Exception:
        a = 0.0
    data.append((r, a))
    total = total + a
    count = count + 1

# again but for the "north" region only, copy-pasted
north_total = 0
north_count = 0
for l in lines:
    if l.strip() == "":
        continue
    parts = l.split(",")
    r = parts[0]
    a = parts[1]
    try:
        a = float(a)
    except Exception:
        a = 0.0
    if r == "north":
        north_total = north_total + a
        north_count = north_count + 1

mean = total / count if count > 0 else 0
north_mean = north_total / north_count if north_count > 0 else 0

print("rows", count)
print("total", total)
print("mean", mean)
print("north_total", north_total)
print("north_mean", north_mean)
