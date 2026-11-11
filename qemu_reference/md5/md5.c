/* MD5 of the 3-byte message "abc" (one 64-byte block, padding done by hand). RV32I only, no library calls.
   Expected digest 900150983cd24fb0d6963f7d28e17f72, stored as 4 little-endian words at RESULT_BASE. */
#ifndef RAM_BASE
#define RAM_BASE 0
#endif
#define RESULT_BASE (RAM_BASE + 0x2000)

static const unsigned int K[64] = {
    0xd76aa478u, 0xe8c7b756u, 0x242070dbu, 0xc1bdceeeu,
    0xf57c0fafu, 0x4787c62au, 0xa8304613u, 0xfd469501u,
    0x698098d8u, 0x8b44f7afu, 0xffff5bb1u, 0x895cd7beu,
    0x6b901122u, 0xfd987193u, 0xa679438eu, 0x49b40821u,
    0xf61e2562u, 0xc040b340u, 0x265e5a51u, 0xe9b6c7aau,
    0xd62f105du, 0x02441453u, 0xd8a1e681u, 0xe7d3fbc8u,
    0x21e1cde6u, 0xc33707d6u, 0xf4d50d87u, 0x455a14edu,
    0xa9e3e905u, 0xfcefa3f8u, 0x676f02d9u, 0x8d2a4c8au,
    0xfffa3942u, 0x8771f681u, 0x6d9d6122u, 0xfde5380cu,
    0xa4beea44u, 0x4bdecfa9u, 0xf6bb4b60u, 0xbebfbc70u,
    0x289b7ec6u, 0xeaa127fau, 0xd4ef3085u, 0x04881d05u,
    0xd9d4d039u, 0xe6db99e5u, 0x1fa27cf8u, 0xc4ac5665u,
    0xf4292244u, 0x432aff97u, 0xab9423a7u, 0xfc93a039u,
    0x655b59c3u, 0x8f0ccc92u, 0xffeff47du, 0x85845dd1u,
    0x6fa87e4fu, 0xfe2ce6e0u, 0xa3014314u, 0x4e0811a1u,
    0xf7537e82u, 0xbd3af235u, 0x2ad7d2bbu, 0xeb86d391u
};
static const unsigned char S[64] = {
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21
};

static void md5_block(const unsigned int *M, unsigned int *out) {
    unsigned int a = 0x67452301u, b = 0xefcdab89u, c = 0x98badcfeu, d = 0x10325476u;
    for (int i = 0; i < 64; i++) {
        unsigned int f;
        int g;
        if (i < 16)      { f = (b & c) | (~b & d); g = i; }
        else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
        else if (i < 48) { f = b ^ c ^ d;          g = (3 * i + 5) & 15; }
        else             { f = c ^ (b | ~d);       g = (7 * i) & 15; }
        f = f + a + K[i] + M[g];
        a = d; d = c; c = b;
        b = b + ((f << S[i]) | (f >> (32 - S[i])));
    }
    out[0] = a + 0x67452301u; out[1] = b + 0xefcdab89u;
    out[2] = c + 0x98badcfeu; out[3] = d + 0x10325476u;
}

#ifdef HOST_TEST
#include <stdio.h>
int main(void) {
    unsigned int M[16] = {0x80636261u, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 24, 0}, o[4];
    md5_block(M, o);
    for (int i = 0; i < 4; i++) for (int j = 0; j < 4; j++) printf("%02x", (o[i] >> (8 * j)) & 255);
    printf("\n");
    return 0;
}
#else
static volatile unsigned int * const status = (unsigned int *)(RESULT_BASE - 4);
static volatile unsigned int * const result = (unsigned int *)RESULT_BASE;

static const unsigned int MSG[16] = {0x80636261u, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 24, 0};

int main(void) {
    unsigned int o[4];
    *status = 0xBEEF0001;
#ifdef REPS   /* optional: hash the same block REPS times (speed experiments) */
    for (int rep = 0; rep < REPS; rep++)
#endif
    md5_block(MSG, o);
    for (int i = 0; i < 4; i++) result[i] = o[i];
    *status = 0xBEEF0002;
    while (1) {}
    return 0;
}
#endif
