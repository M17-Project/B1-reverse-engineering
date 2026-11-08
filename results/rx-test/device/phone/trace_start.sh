T=/sys/kernel/debug/tracing; P=$(pidof com.w2cyk.android.rfinder); echo "app pid $P"
ls -l /proc/$P/fd | grep -E "ttyS0|intercom"
TIDS=$(ls /proc/$P/task | sed 's/^/common_pid==/' | paste -sd'|' | sed 's/|/ || /g')
F="(id==63 || id==64 || id==29 || id==56 || id==57) && ($TIDS)"
echo 0 > $T/tracing_on; echo > $T/trace; echo 8192 > $T/buffer_size_kb
echo "$F" > $T/events/raw_syscalls/sys_enter/filter; echo "$F" > $T/events/raw_syscalls/sys_exit/filter
echo 1 > $T/events/raw_syscalls/enable; echo 1 > $T/tracing_on
# watchdog: stop tracing after 15 min if trace_stop.sh was not run
nohup sh -c 'sleep 900; T=/sys/kernel/debug/tracing; echo 0 > $T/tracing_on; echo 0 > $T/events/raw_syscalls/enable' >/dev/null 2>&1 &
echo $! > /data/local/tmp/rx/trace_watchdog.pid; echo "tracing on=$(cat $T/tracing_on), watchdog pid $(cat /data/local/tmp/rx/trace_watchdog.pid), started $(date +%T)"
