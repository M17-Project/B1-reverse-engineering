# capture inside the running session (no BT-mode toggling)
cd /data/local/tmp; timeout $((${2:-20}+10)) ./tinycap rx/$1.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t ${2:-20} >/dev/null 2>&1; echo "cap $1 rc=$? $(date +%T)"
