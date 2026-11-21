/* NDS32 RAM reader; protocol in FIRMWARE_DUMP.md. */
 .macro tx reg
1: lwi $t0, [$s7 + 0x14]
 andi $t0, $t0, 0x20
 beqz $t0, 1b
 swi \reg, [$s7 + 0]
 .endm
 .macro rx reg
1: lwi $t0, [$s7 + 0x14]
 andi $t0, $t0, 1
 beqz $t0, 1b
 lwi \reg, [$s7 + 0]
 andi \reg, \reg, 0xff
 .endm
 .text
 .globl _start
_start:
 sethi $sp, 0x21f
 ori $sp, $sp, 0
 sethi $s7, 0xc2060
 ori $s7, $s7, 0
 la $s3, banner
banner_loop:
 lbi.bi $a0, [$s3], 1
 beqz $a0, request
 tx $a0
 j banner_loop
request:
 rx $s5
 movi $t1, 0x51
 beq $s5, $t1, reset
 movi $t1, 0x4d
 beq $s5, $t1, memory
 movi $t1, 0x46
 bne $s5, $t1, request
 jal get_word
 mov55 $s6, $a0
memory:
 jal get_word
 mov55 $s0, $a0
 jal get_word
 mov55 $s4, $a0
 movi $t1, 4096
 slt $t2, $t1, $s4
 bnez $t2, request
 mov55 $s3, $s0
 movi $t1, 0x46
 bne $s5, $t1, frame
 
 /* 32-byte SPI reads avoid RX FIFO overrun with caches disabled. */
 movi55 $s8, 0
flash_chunk:
 add $a0, $s0, $s8
 sethi $a1, 0x210
 add $a1, $a1, $s8
 sub $a2, $s4, $s8
 movi $t1, 32
 slt $t2, $t1, $a2
 cmovn $a2, $t1, $t2
 jral $lp, $s6
 addi $s8, $s8, 32
 slt $t2, $s8, $s4
 bnez $t2, flash_chunk
 sethi $s3, 0x210
 ori $s3, $s3, 0
frame:
 sethi $a0, 0x31445
 ori $a0, $a0, 0x255
 jal put_word
 mov55 $a0, $s0
 jal put_word
 mov55 $a0, $s4
 jal put_word
 mov55 $s1, $s4
 movi55 $s2, 0
data_loop:
 beqz $s1, checksum
 lbi.bi $a0, [$s3], 1
 add45 $s2, $a0
 tx $a0
 subi45 $s1, 1
 j data_loop
checksum:
 mov55 $a0, $s2
 jal put_word
 j request
get_word:
 movi55 $a0, 0
 movi55 $t2, 0
2: rx $t3
 sll $t3, $t3, $t2
 or $a0, $a0, $t3
 addi45 $t2, 8
 movi $t4, 32
 bne $t2, $t4, 2b
 ret $lp
put_word:
 movi55 $t2, 4
3: andi $t3, $a0, 0xff
 tx $t3
 srli $a0, $a0, 8
 subi45 $t2, 1
 bnez $t2, 3b
 ret $lp
reset:
 sethi $t1, 0xc2000
 ori $t1, $t1, 0
 lwi $t0, [$t1 + 0x3c]
 ori $t0, $t0, 1
 swi $t0, [$t1 + 0x3c]
4: j 4b
 .align 2
banner:
 .asciz "UM982RAM1\r\n"
