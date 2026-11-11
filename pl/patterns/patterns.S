    .section .text
    .globl _start
_start:
    li x1, 0x55555555
    li x2, 0xaaaaaaaa
    li x3, 0xdeadbeef
    li x4, 0xcafebabe
    li x5, 0x0badf00d
    li x6, 0xffffffff
    li x7, 0x40000000
    li x8, 0x80020000
    li x9, 0xc0000001
    li x10, 0x7fffffff
    li x11, 0x00000001
    li x12, 0x12345678
    li x13, 0x52e6b438
    li x14, 0xf2a74de4
    li x15, 0x269e0d37
    li x16, 0x6513270e
    li x17, 0xa6a3a450
    li x18, 0x0c5c7fd0
    li x19, 0x128b2f33
    li x20, 0xd23f0824
    li x21, 0x892f902b
    li x22, 0x1818e811
    li x23, 0x5d9dc9f8
    li x24, 0x9531985d
    li x25, 0x0ed90475
    li x26, 0xe8e25d94
    li x27, 0x81e74ef5
    li x28, 0x36f675cc
    li x29, 0x099950d8
    li x30, 0x1600a35a
    li x31, 0x6f03675a
done:
    j done
