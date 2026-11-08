T=/sys/kernel/debug/tracing
echo 0 > $T/tracing_on; echo 0 > $T/events/raw_syscalls/enable
cat $T/trace > /data/local/tmp/rx/apptrace_action.txt
echo 0 > $T/events/raw_syscalls/sys_enter/filter; echo 0 > $T/events/raw_syscalls/sys_exit/filter; echo > $T/trace; echo 7 > $T/buffer_size_kb
W=$(cat /data/local/tmp/rx/trace_watchdog.pid 2>/dev/null); [ -n "$W" ] && { kill $(pgrep -P $W) $W 2>/dev/null; rm /data/local/tmp/rx/trace_watchdog.pid; }
echo "stopped $(date +%T); lines $(wc -l < /data/local/tmp/rx/apptrace_action.txt); on=$(cat $T/tracing_on) ev=$(cat $T/events/raw_syscalls/enable) buf=$(cat $T/buffer_size_kb)"
