'''
RGH 1.2.3
The method that sounds like a shitpost, but isn't.

This is basically RGH3 but on a microcontroller for better precision.

Status: Not working, gets stuck on POST 0x22 every time.

Bugs:
- I2C can shit itself several times. SoftI2C can crap out, or HANA/SMC
  communication can have problems leading to RROD 0010. Both mean you
  have to restart the script and/or the system after about 10 attempts.
'''

from time import sleep, ticks_us
from machine import Pin,mem32
import rp2
from rp2 import PIO

from machine import SoftI2C,freq

# POST monitoring must be done as fast as possible
RP2040_GPIO_IN = 0xD0000004
POST_BITS_MASK = 0xFF << 15
POST_D5        = 0xD5 << 15
POST_D6        = 0xD6 << 15


# actual logical bits are reversed
# all are connected to the POST pins via diodes as in RGH3
# DBG_CPU_POST_OUT7 = post bit 0 for RGH 1.2
# DBG_CPU_POST_OUT6 = post bit 1 for RGH 1, 3
DBG_CPU_POST_OUT0 = Pin(22, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT1 = Pin(21, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT2 = Pin(20, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT3 = Pin(19, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT4 = Pin(18, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT5 = Pin(17, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT6 = Pin(16, Pin.IN, Pin.PULL_UP)
DBG_CPU_POST_OUT7 = Pin(15, Pin.IN, Pin.PULL_UP)

# outputs
CPU_RESET           = Pin(14, Pin.IN) # will switch to output later
CPU_PLL_BYPASS      = Pin(13, Pin.OUT)


@rp2.asm_pio(set_init=[PIO.OUT_LOW, PIO.IN_LOW])
def rgh123():
    pull(noblock)                         # 0
    mov(x, osr)                           # 1
    pull(noblock)                         # 2
    mov(y, osr)                           # 3
    wait(0, pin, 1)                       # 4
    wait(1, pin, 0)                       # 5
    label("6")
    jmp(x_dec, "6")                       # 6
    set(pins, 1)                          # 7
    wait(1, pin, 1)                       # 8
    label("9")
    jmp(y_dec, "9")                       # 9
    set(pindirs, 3)                  [3]  # 10
    set(pins, 3)                          # 11
    set(pindirs, 1)                       # 12
    set(pins, 0)                          # 13
    push(noblock)                         # 14
    wrap_target()
    nop()                                 # 15
    wrap()

pio_sm = None

def monitor_post():
    last_post = 0
    while True:
        this_post = mem32[RP2040_GPIO_IN] >> 15
        if this_post != last_post:
            print(f"{this_post:08x}")
            last_post = this_post

def init_sm(reset_assert_delay):
    global pio_sm
    pio_sm = rp2.StateMachine(0, rgh123, freq = 48000000, in_base=DBG_CPU_POST_OUT7, set_base=CPU_PLL_BYPASS)

    pio_sm.active(0)
    pio_sm.restart()
    pio_sm.active(0)
    print("restarted sm")

    # set /RESET to: input enable, full power drive, pullup/pulldown disabled, schmitt triggered, fast slew rate
    # it's unbelievable that micropython sets the slew rate to slow by default...
    mem32[0x4001c004 + (14*4)] = 0b01110011
    if mem32[0x4001c004 + (14*4)] == 0b01110011:
        print("full steam ahead!!")
    else:
        raise RuntimeError("cannot set I/O drive...")

    # set slew rate to fast for PLL too
    mem32[0x4001c004 + (13*4)] |= 1

    # this is nowhere near precise and has to be tuned
    pll_delay = 72686000

    # reset delay is around 26.924 ms in RGH3
    # that's about 1292352 cycles @ 48 MHz
    # actual working or plausible delay value not found yet
    reset_delay = reset_assert_delay

    print("using these settings")
    print(f"- pll delay {pll_delay}")
    print(f"- reset delay {reset_delay}")

    # populate FIFO - when PIO starts, it'll grab both these values immediately
    pio_sm.put(pll_delay)
    pio_sm.put(reset_delay)
    print("buffered FIFO")


def do_reset_glitch() -> int:
    i2c = SoftI2C(sda=Pin(8),scl=Pin(9),freq=100000)

    while (mem32[RP2040_GPIO_IN] & POST_BITS_MASK) != POST_D5:
        pass 
    while (mem32[RP2040_GPIO_IN] & POST_BITS_MASK) != POST_D6:
        pass

    print("0xD6 arrived, start PIO")
    pio_sm.active(1)

    # default clock is [ 0x14, 0x44, 0xE8, 0x08 ]
    # 27 MHz mode is [ 0x14, 0x44, 0xE8, 0x28 ]
    # 15432 also found [ 0x14, 0x44, 0xE8, 0x88 ], maybe this is RGH3's 10 MHz mode?
    # i2c.writeto_mem(0x70, 0xCE, bytearray([0x04, 0x14, 0x44, 0xE8, 0x28]))

    

    last_post = 0

    ticks_DA = 0
    ticks_after_DA = ()

    try:
        while True:
            v = mem32[RP2040_GPIO_IN]
            t = ticks_us()
            this_post = (v >> 15) & 0xFF

            if last_post != 0xD8 and this_post == 0xD8:
                print("0xD8 arrived, send I2C")
                i2c.writeto_mem(0x70, 0xCE, bytearray([0x04, 0x14, 0x44, 0xE8, 0x28]))

            if last_post != 0xDA and this_post == 0xDA:
                ticks_DA = t

                # block until PIO is done
                print("awaiting PIO finish...")
                pio_sm.get()
                i2c.writeto_mem(0x70, 0xCE, bytearray([0x04, 0x14, 0x44, 0xE8, 0x08]))


                print("PIO is done")


                # debugging
                '''
                while mem32[RP2040_GPIO_IN] == v:
                    pass
                ticks_after_DA = ticks_us()
                '''
            
            if this_post != last_post:
                print(f"{this_post:02x}")
                last_post = this_post
                if this_post == 0xDB:
                    print("got candidate!!!")

            if this_post == 0x00:
                print("FAIL: SMC timed out")
                return 0

            if this_post == 0xF2:
                print("FAIL: hash check mismatch")
                
                # this time is nowhere near accurate thanks to micropython's interpreted nature
                # but it is close to what it should be, and that's what counts
                #
                # note also that if your reset wait value is too high, it will
                # cause this result to be skewed upwards.
                print(f"-> DA -> F2 = {t-ticks_DA} usec")
                return 1
    finally:
        i2c.writeto_mem(0x70, 0xCE, bytearray([0x04, 0x14, 0x44, 0xE8, 0x08]))

def do_reset_glitch_loop():
    # fails around 1366368 / 28447 usec

    freq(192000000)
    
    # 0xDB candidates are: 1292328, 1292329, 1292330
    # this does get CB_B executing, but then the CPU crashes at 0x22.
    # occasionally weird POST codes show up (0x88, 0x44, etc.)
    #
    # it's probably necessary to make a "glitch3" type image that's just a standard
    # glitch2 image, but with the RGH3 stub in CB_B. tried making this myself but
    # all it managed to do was brick the console...
    reset_trial = 1292329 # 349821 # int(48 * 7296) # int(48 * 7400) # = 349821
    
    while True:
        print(f"start trial of: {reset_trial}")

        init_sm(reset_trial)

        result = do_reset_glitch()

        if result == 2:
            init_sm(0)
            return
        # elif result != 0:
        # reset_trial -= 1
