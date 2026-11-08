// m17_reenc: decode M17 stream frames from a soft symbol stream, re-encode them with libm17's own
// transmit chain, and report pre-FEC bit errors per frame.
//
//   m17_reenc symbols.f32 starts.txt out_ref.f32 > report.tsv
//
// symbols.f32 : float32 soft symbols (nominal +-1/+-3), one per symbol
// starts.txt  : one integer per line, index of the first syncword symbol of each frame slot
// out_ref.f32 : 192 re-encoded symbols per listed frame slot (same order as starts.txt)
// report      : slot, start, fn, lich_cnt, viterbi_e, prefec_bit_errors (of 368), lich bytes (hex)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <m17.h>

static int bits_of(float s, int b) // dibit of a symbol: +3 -> 01, +1 -> 00, -1 -> 10, -3 -> 11
{
    int d = (s >= 2.0f) ? 1 : (s >= 0.0f) ? 0 : (s >= -2.0f) ? 2 : 3;
    return (d >> b) & 1;
}

int main(int argc, char **argv)
{
    if (argc != 4) { fprintf(stderr, "usage: %s symbols.f32 starts.txt out_ref.f32\n", argv[0]); return 2; }
    FILE *fs = fopen(argv[1], "rb"), *ft = fopen(argv[2], "r"), *fo = fopen(argv[3], "wb");
    if (!fs || !ft || !fo) { perror("open"); return 1; }
    fseek(fs, 0, SEEK_END); long n = ftell(fs) / 4; fseek(fs, 0, SEEK_SET);
    float *sym = malloc(n * sizeof(float));
    if (fread(sym, 4, n, fs) != (size_t)n) { fprintf(stderr, "short read\n"); return 1; }

    long start; int slot = 0;
    printf("slot\tstart\tfn\tlich_cnt\te\tbit_err\tlich\n");
    while (fscanf(ft, "%ld", &start) == 1)
    {
        float ref[SYM_PER_FRA];
        memset(ref, 0, sizeof(ref));
        if (start < 0 || start + SYM_PER_FRA > n) { fwrite(ref, 4, SYM_PER_FRA, fo); slot++; continue; }
        const float *pld = &sym[start + SYM_PER_SWD];

        uint8_t frame_data[16], lich[5], lich_cnt = 0; uint16_t fn = 0;
        uint32_t e = decode_str_frame(frame_data, lich, &fn, &lich_cnt, pld);

        int bit_err = -1;
        if (lich_cnt < 6)
        {
            lsf_t lsf; memset(&lsf, 0, sizeof(lsf));
            memcpy((uint8_t *)&lsf + lich_cnt * 5, lich, 5);   // the only LSF chunk gen_frame uses
            if (gen_frame(ref, frame_data, FRAME_STR, &lsf, lich_cnt, fn) == 0)
            {
                bit_err = 0;
                for (int i = 0; i < SYM_PER_PLD; i++)
                    for (int b = 0; b < 2; b++)
                        bit_err += bits_of(pld[i], b) != bits_of(ref[SYM_PER_SWD + i], b);
            }
            else memset(ref, 0, sizeof(ref));
        }
        fwrite(ref, 4, SYM_PER_FRA, fo);
        printf("%d\t%ld\t%u\t%u\t%.2f\t%d\t%02X%02X%02X%02X%02X\n", slot, start, fn & 0x7FFF, lich_cnt,
               (float)e / 0xFFFF, bit_err, lich[0], lich[1], lich[2], lich[3], lich[4]);
        slot++;
    }
    free(sym); fclose(fs); fclose(ft); fclose(fo);
    return 0;
}
