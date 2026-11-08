# usage: sh atcmd.sh "AT+..." [wait_s]   -- sends one line + \r, prints reply bytes
# ttyS0 is raw with VMIN=0/VTIME=0, so a single cat exits at once; loop it for the whole window.
cd /data/local/tmp; W=${2:-2}; : > rx/at_resp.bin
timeout $((W+1)) sh -c 'while :; do cat /dev/ttyS0; done' >> rx/at_resp.bin 2>/dev/null & R=$!
sleep 0.3; printf '%s\r' "$1" > /dev/ttyS0; sleep $W; wait $R 2>/dev/null
echo ">> $1  [$(wc -c < rx/at_resp.bin) bytes]"; od -An -c rx/at_resp.bin | head -10
