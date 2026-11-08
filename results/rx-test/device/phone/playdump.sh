# read-only: start playback, then dump mixer, audio policy, amp regs and kernel log while it plays
cd /data/local/tmp; T=$1; dmesg > rx/pd_$T.dmesg0
am start -a android.intent.action.VIEW -d file:///sdcard/Download/c2b_rep.wav -t audio/wav >/dev/null 2>&1
sleep 2
./tinymix -D 0 contents > rx/pd_$T.mix 2>&1
cat /sys/bus/i2c/drivers/aw87329/3-0058/reg > rx/pd_$T.amp
dumpsys media.audio_policy > rx/pd_$T.policy 2>&1
dumpsys media.audio_flinger > rx/pd_$T.flinger 2>&1
dmesg > rx/pd_$T.dmesg1
echo "dumped $T $(date +%T), hw_pd $(cat /sys/bus/platform/drivers/intercom_driver/intercom/hw_pd), $(media volume --stream 3 --get 2>/dev/null | tail -1)"
