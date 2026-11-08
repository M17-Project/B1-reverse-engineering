T=/sys/kernel/debug/tracing; P=$(pidof com.w2cyk.android.rfinder)
echo "pid $P"; ls -l /proc/$P/fd 2>/dev/null | grep -E "ttyS0|intercom" 
TIDS=$(ls /proc/$P/task | sed 's/^/common_pid==/' | paste -sd'|' | sed 's/|/ || /g')
F="(id==63 || id==64 || id==29 || id==56 || id==57) && ($TIDS)"
echo 0 > $T/tracing_on; echo > $T/trace; echo 8192 > $T/buffer_size_kb
echo "$F" > $T/events/raw_syscalls/sys_enter/filter; echo "$F" > $T/events/raw_syscalls/sys_exit/filter
echo 1 > $T/events/raw_syscalls/enable; echo 1 > $T/tracing_on
sleep ${1:-30}
echo 0 > $T/tracing_on; echo 0 > $T/events/raw_syscalls/enable
cat $T/trace > /data/local/tmp/rx/apptrace.txt
echo 0 > $T/events/raw_syscalls/sys_enter/filter; echo 0 > $T/events/raw_syscalls/sys_exit/filter; echo > $T/trace; echo 7 > $T/buffer_size_kb
echo "lines $(wc -l < /data/local/tmp/rx/apptrace.txt)"
