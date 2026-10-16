#!/bin/bash
# QNN asks the DSP for API-version-suffixed skel names (libFoo.so.2); the packages ship only the bare name.
set -u
D=$(readlink -f /usr/lib/dsp/cdsp) || exit 0
cd "$D" || exit 0
for f in libQnn*.so libCalculator_skel.so; do
    [ -e "$f" ] || continue
    [ -e "$f.2" ] || ln -sfn "$f" "$f.2"
done
[ -e libcalculator_skel.so ] || ln -sfn libCalculator_skel.so libcalculator_skel.so
# qcom-fastrpc-dev provided the unversioned dev symlinks; Radxa's runtime package does not.
for n in cdsprpc adsprpc sdsprpc; do
    t=/usr/lib/aarch64-linux-gnu/lib${n}.so
    [ -e "$t" ] || { [ -e "$t.1" ] && ln -sfn lib${n}.so.1 "$t"; }
done
exit 0
