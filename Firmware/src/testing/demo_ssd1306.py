"""
Demo based on the testOL.py script that comes wiht the SSD1306 MP lib - heavily
modified for asyncio operation.
"""

import random
import uasyncio as asyncio
from ssd1306 import SSD1306_I2C
from config import OLED_ADDR, OLED_W, OLED_H


def centerText(screen, txt, py):
    """
    Centers the given text on the screen - brute forcibly :-(
    """
    px = int((128 - (len(txt) * 8)) / 2)
    screen.text(txt, px, py)


async def demoOLED(i2c):
    """
    Demo translated from the testOLED.py script that caomes with the SDD1306
    lib.
    """
    # pylint: disable=too-many-statements

    oled = SSD1306_I2C(OLED_W, OLED_H, i2c, OLED_ADDR)

    while True:
        # Fill and clear screen
        oled.fill(1)
        oled.show()
        await asyncio.sleep(1)
        oled.fill(0)
        oled.show()

        # Hello World!
        oled.text("Hello", 1, 4)
        oled.show()
        await asyncio.sleep(0.5)
        oled.text("World!", 45, 4)
        oled.show()
        await asyncio.sleep(1)

        # Power off and on
        oled.poweroff()
        await asyncio.sleep(1)
        oled.poweron()
        await asyncio.sleep(1)

        # Demo inverting
        oled.invert(1)
        await asyncio.sleep(1)
        oled.invert(0)
        await asyncio.sleep(1)

        # Contrast changing
        for i in range(0, 256, 16):
            oled.fill_rect(0, 50, 128, 63, 0)
            oled.text(f"Contrast {i}", 0, 50)
            oled.show()
            oled.contrast(i)
            await asyncio.sleep(0.1)

        # Full contrast
        oled.fill_rect(0, 50, 128, 63, 0)
        oled.text("Contrast 255", 0, 50)
        oled.show()
        oled.contrast(255)
        await asyncio.sleep(1)

        # Draw lines
        oled.fill(0)
        centerText(oled, "LINES", 5)
        oled.show()
        for i in range(0, 128, 3):
            oled.line(i, 16, 127 - i, 63, 1)
            if (i / 2) > 15 and i % 2 == 0:
                oled.line(0, int(i / 2), 127, 63 - int(i / 2) + 16, 1)
            oled.show()
            await asyncio.sleep(0.1)
        await asyncio.sleep(2)

        # Random connected lines
        oled.fill(0)
        lines = []
        for i in range(0, 100):
            lines.append(random.randrange(128))
            lines.append(random.randrange(64))
        oled.drawConnectedLines(lines)
        oled.show()
        await asyncio.sleep(2)

        # Random lines
        oled.fill(0)
        lines = []
        for i in range(0, 100):
            lines.append(random.randrange(128))
            lines.append(random.randrange(64))
        oled.drawLines(lines)
        oled.show()
        await asyncio.sleep(2)

        # Draw MP Logo
        oled.fill(0)
        oled.show()
        oled.fill_rect(0, 16, 32, 48, 1)
        oled.fill_rect(2, 18, 28, 44, 0)
        oled.vline(9, 24, 38, 1)
        oled.vline(16, 18, 38, 1)
        oled.vline(23, 24, 36, 1)
        oled.fill_rect(26, 56, 2, 4, 1)
        oled.text("MicroPython", 40, 16, 1)
        oled.text("SSD1306", 40, 28, 1)
        oled.text("OLED 128x64", 40, 40, 1)
        oled.show()
        await asyncio.sleep(2)

        # Show rotate 180
        oled.rotate = True
        oled.show()
        await asyncio.sleep(2)
        oled.rotate = False
        oled.show()
        await asyncio.sleep(1)

        # Circles and ovals
        oled.fill(0)
        oled.drawCircle(64, 32, 15)
        oled.show()
        await asyncio.sleep(0.5)
        clr = 1
        rd = 15
        for i in range(0, 5):
            oled.fillOval(64, 32, rd, rd - 2, clr)
            oled.show()
            await asyncio.sleep(0.5)
            clr = 1 - clr
            rd -= 3
