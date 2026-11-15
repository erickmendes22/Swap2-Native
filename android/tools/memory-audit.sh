#!/system/bin/sh
# Snapshot only the two emulator packages; no settings, caches or processes changed.
# Run using root on Android: su -c 'sh /sdcard/Download/swap-memory-audit.sh'
# Compare two snapshots of the same loaded scene. This is not an FPS benchmark.
set -u
umask 077
PROC_ROOT=${SWAP_AUDIT_PROC_ROOT:-/proc}
SYS_ROOT=${SWAP_AUDIT_SYS_ROOT:-/sys}
FILES_ROOT=${SWAP_AUDIT_FILES_ROOT:-/sdcard/Android/data}
OUT=${1:-/sdcard/Download/swap-memory-$(date +%Y%m%d-%H%M%S).txt}
if [ "$OUT" != - ]; then
    exec 3>"$OUT" || exit 1
else
    exec 3>&1
fi
say() { printf '%s\n' "$*" >&3; }
read_file() {
    if [ -r "$1" ]; then cat "$1" >&3 2>/dev/null || say "UNAVAILABLE: $1 (process ended or access denied)"
    else say "UNAVAILABLE: $1 (absent or access denied)"; fi
}
say 'Swap/Banana physical-memory snapshot v1'
say "Time: $(date '+%Y-%m-%d %H:%M:%S %z')"
say 'Units: smaps and meminfo use KiB; sysfs GPU/ZRAM values retain their original units.'
say 'PSS proportions shared pages. RSS counts mappings. SwapPss is swapped logical data, not compressed ZRAM bytes.'
say 'GPU mappings are already included in smaps. Do not add GPU counters to PSS: they can overlap.'
say 'dumpsys meminfo also reports graphics memtrack; retain its full output for comparison.'
say 'No missing/denied reading is treated as zero.'
if ! command -v awk >/dev/null 2>&1; then
    if [ -x /data/data/com.termux/files/usr/bin/awk ]; then
        PATH=/data/data/com.termux/files/usr/bin:$PATH
        export PATH
    fi
fi
if ! command -v awk >/dev/null 2>&1; then
    say 'ERROR: awk unavailable; no memory comparison was made.'
    exit 3
fi
TARGET=${SWAP_AUDIT_TARGET:-}
WAIT_SECONDS=${SWAP_AUDIT_WAIT_SECONDS:-60}
case "$TARGET" in ''|com.swap2native.ootv11ios|dev.bananative.android) ;; *) say 'ERROR: invalid target package'; exit 4;; esac
case "$WAIT_SECONDS" in ''|*[!0-9]*) say 'ERROR: invalid wait duration'; exit 4;; esac
[ "$WAIT_SECONDS" -le 60 ] || WAIT_SECONDS=60
elapsed=0
while :; do
    if [ -n "${SWAP_AUDIT_PS_LIST_FILE:-}" ]; then
        inventory=$(cat "$SWAP_AUDIT_PS_LIST_FILE") || exit 1
    else
        inventory=$(ps -A -o PID,ARGS 2>/dev/null) || { say 'ERROR: process inventory unavailable'; exit 1; }
    fi
    processes=$(printf '%s\n' "$inventory" | awk '
    $1 ~ /^[0-9]+$/ {
     for(i=1;i<=2;i++) {
      p=i==1?"com.swap2native.ootv11ios":"dev.bananative.android"
      if($2==p || index($2,p ":")==1) {print $1, $2;break}
     }}')
    game=$(printf '%s\n' "$processes" | awk -v target="$TARGET" '
    (target!="" && $2==target ":game") ||
    (target=="" && ($2=="com.swap2native.ootv11ios:game" || $2=="dev.bananative.android:game")) {print $1}')
    [ -z "$game" ] || break
    if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
        if [ -z "$processes" ]; then say 'ERROR: neither emulator package has a running process.'
        else say 'ERROR: launcher found, but the requested :game process is absent. This is NOT a gameplay memory snapshot.'; say "$processes"; fi
        [ "$OUT" = - ] || printf 'Saved error report: %s\n' "$OUT" >&2
        exit 2
    fi
    [ "$elapsed" -ne 0 ] || say "Waiting up to $WAIT_SECONDS seconds for ${TARGET:-either emulator}:game. Return to the loaded game."
    sleep 2
    elapsed=$((elapsed + 2))
done
say "Capture time: $(date '+%Y-%m-%d %H:%M:%S %z'); requested target: ${TARGET:-either}; game PIDs: $game"
say '--- SYSTEM MEMORY BEFORE ---'; read_file "$PROC_ROOT/meminfo"
say '--- MEMORY PRESSURE ---'; read_file "$PROC_ROOT/pressure/memory"
for z in "$SYS_ROOT"/block/zram*/mm_stat; do
    [ -e "$z" ] || continue
    say "--- GLOBAL ZRAM: $z (bytes: orig_data_size compr_data_size mem_used_total, then kernel fields) ---"; read_file "$z"
done
say '--- MATCHED PROCESSES (includes launcher, game and preparation processes) ---'
say "$processes"
printf '%s\n' "$processes" | while read -r pid name; do
    say "=== PROCESS $pid $name ==="
    case "$name" in *:game)
        package=${name%%:*}
        latest=$(ls -t "$FILES_ROOT/$package/files/logs/"*.log 2>/dev/null | head -n 1)
        say '--- RUN IDENTITY AND SAFE MEMORY/RENDER FLAGS ---'
        if [ -n "$latest" ] && [ -r "$latest" ]; then
            say "Log: $latest"
            awk '/^\[nxlaunch\] build / || /env (DM_MEM_FILEBACK|DM_MEM_FILEBACK_KINDS|DM_VK_PLACE_SHADER_POOLS|DM_VK_ALIAS|DM_VK_NDSR|DM_GRAPHICS_SCALE|DM_OPMODE)=/ {print}' "$latest" >&3
            tail -n 250 "$latest" | awk '/timing up to frame/ {last=$0} END {if(last!="")print last;else print "UNAVAILABLE: recent frame timing"}' >&3
        else say 'UNAVAILABLE: current app log'; fi
    ;; esac
    say '--- STATUS ---'
    if [ -r "$PROC_ROOT/$pid/status" ]; then
        awk '/^(Name|State|Pid|PPid|Uid|VmPeak|VmSize|VmRSS|RssAnon|RssFile|RssShmem|VmSwap|Threads):/' "$PROC_ROOT/$pid/status" >&3
    else say 'UNAVAILABLE: status'; fi
    say '--- SMAPS ROLLUP (process mappings only; graphics memtrack is separate) ---'
    read_file "$PROC_ROOT/$pid/smaps_rollup"
    say '--- MAPPINGS BY CATEGORY: RSS_KiB PSS_KiB PrivateDirty_KiB SwapPss_KiB count category ---'
    if [ -r "$PROC_ROOT/$pid/smaps" ]; then
        awk '
        function finish(  c) {
          if(!header)return
          c="other mappings"
          if(path ~ /kgsl|dmabuf|dma_buf|dma_heap/)c="GPU mappings (already in PSS)"
          else if(path ~ /dmsh_vk\.lib|\/shaders\/.*\.lib/)c="translated shader libraries"
          else if(path ~ /dalvik/)c="Java/Dalvik"
          else if(path ~ /nxnative guest/)c="guest named memory"
          else if(path ~ /\[heap\]|scudo|libc_malloc/)c="native allocator"
          else if(path ~ /\/cache\/.*\(deleted\)/)c="unlinked cache files (includes RAM Saver)"
          else if(path ~ /stack/)c="thread stacks"
          else if(path ~ /\.so($| )|\.apk($| )|\/apex\//)c="native code/APK"
          else if(path=="" || path ~ /^\[anon/)c="other anonymous memory"
          else if(path ~ /^\//)c="other file mappings"
          rss[c]+=r;pss[c]+=p;dirty[c]+=d;swap[c]+=s;count[c]++
          if(p>=8192)heavy=heavy sprintf("%12d %12d %12d %12d %s\n",r,p,d,s,header)
          n++
        }
        /^[0-9a-fA-F]+-[0-9a-fA-F]+[[:space:]]/ {
          finish();header=$0;path="";for(i=6;i<=NF;i++)path=path (i==6?"":" ") $i
          r=p=d=s=0;next
        }
        /^Rss:/ {r=$2}
        /^Pss:/ {p=$2}
        /^Private_Dirty:/ {d=$2}
        /^SwapPss:/ {s=$2}
        END {
          finish()
          if(!n){print "UNAVAILABLE: no smaps mappings read";exit 1}
          for(c in count)printf "%12d %12d %12d %12d %8d %s\n",rss[c],pss[c],dirty[c],swap[c],count[c],c
          print "--- LARGE MAPPINGS (PSS at least 8 MiB), same columns, then original map header ---"
          printf "%s",heavy
        }' "$PROC_ROOT/$pid/smaps" >&3 || say 'UNAVAILABLE: smaps incomplete or process exited'
    else say 'UNAVAILABLE: smaps (root may be required)'; fi
    say '--- ANDROID DUMPSYS MEMINFO (includes memtrack when supported) ---'
    if command -v dumpsys >/dev/null 2>&1; then
        dumpsys -t 10 meminfo -a "$pid" >&3 2>&3 || say 'UNAVAILABLE: dumpsys failed or timed out'
    else say 'UNAVAILABLE: dumpsys command'; fi
    for f in gpumem gpumem_mapped; do
        fpath="$SYS_ROOT/class/kgsl/kgsl/proc/$pid/$f"
        say "--- KGSL $f (driver-provided units, may overlap PSS) ---"; read_file "$fpath"
    done
    say "=== END PROCESS $pid ==="
done
for gamepid in $game; do
    if [ ! -r "$PROC_ROOT/$gamepid/status" ]; then
        say "ERROR: game PID $gamepid ended during the snapshot; this capture is incomplete."
        exit 2
    fi
done
say '--- SYSTEM MEMORY AFTER ---'; read_file "$PROC_ROOT/meminfo"
say 'End of snapshot. This capture does not change render settings or terminate apps.'
[ "$OUT" = - ] || printf 'Saved: %s\n' "$OUT" >&2
