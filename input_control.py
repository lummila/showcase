from machine import Pin, ADC, I2C
from filefifo import Filefifo
from fifo import Fifo
from ssd1306 import SSD1306_I2C
import time


# The rotary knob button
class Button:
    def __init__(self):
        self.sw = Pin(12, Pin.IN, Pin.PULL_UP)
        self.btn_fifo = Fifo(30, typecode="i")
        self.sw.irq(handler=self.btn_handler, trigger=Pin.IRQ_RISING, hard=False)
        self.last_press_time = 0  # Variable to store the last press time

    def btn_handler(self, pin):
        current_time = time.ticks_ms()
        if current_time - self.last_press_time >= 100:  # Check for debounce time
            self.last_press_time = current_time
            self.btn_fifo.put(1)  # Put button press event into FIFO


# The rotary knob turning handling
class Rotary:
    def __init__(self):
        self.right = Pin(10, mode=Pin.IN, pull=Pin.PULL_UP)
        self.left = Pin(11, mode=Pin.IN, pull=Pin.PULL_UP)
        self.rot_fifo = Fifo(100, typecode="i")
        self.right.irq(
            handler=self.rot_handler, trigger=Pin.IRQ_RISING, hard=True
        )  # Interrupter
        self.dir = True
        self.prev_dir = True
        self.val = 0
        self.rotary_filter = 0

    # Rotating encoder left or right
    def rot_handler(self, pin):
        if self.left():
            self.val = -1
            self.dir = False
        else:
            self.val = 1
            self.dir = True

        self.rotary_filter += self.val
        if self.dir != self.prev_dir:
            self.rotary_filter = 0
        if abs(self.rotary_filter) >= 3:
            # Here the valid values go into rotary fifo
            self.rot_fifo.put(self.val)
            self.rotary_filter = 0

        self.prev_dir = self.dir


# The pulse sensor, handlers and whatnot are assigned in Measure
class Sensor:
    def __init__(self):
        self.adc = ADC(Pin(26, Pin.IN))
        self.adc_fifo = Fifo(500)


# Home for all the inputs
class Inputs(Button, Rotary, Sensor):
    def __init__(self):
        Button.__init__(self)
        Rotary.__init__(self)
        Sensor.__init__(self)


# Home for everything display-related.
class Screen(Inputs):
    def __init__(self):
        # Inputs init
        Inputs.__init__(self)

        # Pins for OLED
        self.OLED_SDA = 14  # Data
        self.OLED_SCL = 15  # Clock
        # Initialize I2C to use OLED
        self.i2c = I2C(1, scl=Pin(self.OLED_SCL), sda=Pin(self.OLED_SDA), freq=400000)

        self.OLED_WIDTH = 128
        self.OLED_HEIGHT = 64
        self.TEXT_HEIGHT = 15
        self.CURRENT_SCREEN = 0
        self.MENU_ROWS = 3

        self.oled = SSD1306_I2C(self.OLED_WIDTH, self.OLED_HEIGHT, self.i2c)
        self.selected_row = 0  # Set starting value of row selector for the menu

        # Current menu states
        self.main_menu = True
        self.hr_menu = False
        self.hrv_menu = False
        self.kubios_menu = False
        self.history_menu = False

    # this function creates selector bar for menus
    def selector(self, direction, maximum_items):
        screen = self.oled
        self.selected_row += direction
        # Limiting max and min values
        if self.main_menu:
            if self.selected_row < 0:
                self.selected_row = 0
        if self.selected_row >= maximum_items:
            self.selected_row = maximum_items

        # Draws rectangle around selection
        if self.selected_row <= -1:
            self.selected_row = -1
            screen.rect(0, 0, 20, self.TEXT_HEIGHT + 2, 1)
        if self.selected_row >= 0:
            screen.rect(
                0,
                self.selected_row * self.TEXT_HEIGHT,
                128,
                self.TEXT_HEIGHT + 2,
                1,
            )

        # Prevent selector not to go to empty space
        if self.kubios_menu or self.hr_menu or self.hrv_menu:
            if self.selected_row >= 2:
                self.selected_row = 2
            if self.selected_row < 2 and direction == -1:
                self.selected_row = -1
            elif self.selected_row - 1 and direction == 1:
                self.selected_row = 2
        return self.selected_row

    # adds text to specific row
    def add_text(
        self, text, x_prosentage, row
    ):  # x_prosentage is prosentage width position in screen
        y_cord = row * self.TEXT_HEIGHT + 4
        self.x_prosentage = int(
            (self.OLED_WIDTH - (len(text) * 8) - 1) / 100 * x_prosentage
        )
        self.oled.text(text, self.x_prosentage, y_cord, 1)

    # this function is for showing menu content
    def show_content(self, menu):
        self.oled.fill(0)
        self.selector(0, self.MENU_ROWS)
        if self.kubios_menu or self.hr_menu or self.hrv_menu:
            for _, item in enumerate(menu):
                # Add text to screen
                self.add_text(item, 50, 2)
        else:
            for i, item in enumerate(menu):
                # Add text to screen
                self.add_text(item, 50, i)
            self.MENU_ROWS = len(menu) - 1
        # adds go back button
        if not self.main_menu:
            self.add_text("<-", 2, 0)

        self.oled.show()

    # Functions for receiving date and time from Kubios API return
    def date_from_file(self, file):
        timestamp: str = file["analysis"]["create_timestamp"]

        date = timestamp[0:10]
        date = date.replace("-", ".")
        date = str(date[8:]) + str(date[4:8]) + str(date[2:4])

        return date

    def time_from_file(self, file):
        timestamp: str = file["analysis"]["create_timestamp"]

        return timestamp[11:16]

    """
    Displays local or kubios HRV calculations. If local:
    hrv_calcs["analysis"]["mean_rr_ms"]: MEAN RR
    hrv_calcs["analysis"]["mean_hr_bpm"]: MEAN HR
    hrv_calcs["analysis"]["rmssd_ms"]: RMSSD
    hrv_calcs["analysis"]["sdnn_ms"]: SDNN

    If kubios, the same as above, and also:
    hrv_calcs["analysis"]["pns_index"]: MEAN RR
    """

    def display_analysis(self, hrv_calcs: dict, is_kubios: bool):
        self.oled.fill(0)
        self.add_text("<-", 2, 0)
        self.MENU_ROWS = 0
        self.selected_row = -1
        time_stamp = time.localtime()

        date_hrv = (
            ("0" if time_stamp[1] < 10 else "")
            + str(time_stamp[1])
            + "."
            + ("0" if time_stamp[2] < 10 else "")
            + str(time_stamp[2])
            + "."
            + str(time_stamp[0])[2:]
        )

        time_hrv = (
            ("0" if time_stamp[3] < 10 else "")
            + str(time_stamp[3])
            + ":"
            + ("0" if time_stamp[4] < 10 else "")
            + str(time_stamp[4])
        )

        # If the processed dictionary is a Kubios analysis
        if is_kubios:
            time_kubios = self.time_from_file(hrv_calcs)

            date_kubios = self.date_from_file(hrv_calcs)

            self.oled.text(time_kubios, 20, 4, 1)
            self.oled.text(date_kubios, 64, 4, 1)
            self.oled.text(
                f"mean rr: {hrv_calcs["analysis"]["mean_rr_ms"]:.01f}", 0, 16, 1
            )
            self.oled.text(
                f"mean hr: {hrv_calcs["analysis"]["mean_hr_bpm"]:.01f}", 0, 24, 1
            )
            self.oled.text(f"rmssd: {hrv_calcs["analysis"]["rmssd_ms"]:.01f}", 0, 32, 1)
            self.oled.text(f"sdnn: {hrv_calcs["analysis"]["sdnn_ms"]:.01f}", 0, 40, 1)
            self.oled.text(f"pns: {hrv_calcs["analysis"]["pns_index"]:.03f}", 0, 48, 1)
            self.oled.text(f"sns: {hrv_calcs["analysis"]["sns_index"]:.03f}", 0, 56, 1)
        # Local HRV dictionary
        else:
            self.oled.text(time_hrv, 20, 4, 1)
            self.oled.text(date_hrv, 64, 4, 1)
            self.oled.text(
                f"mean rr: {hrv_calcs["analysis"]["mean_rr_ms"]:.01f}", 0, 20, 1
            )
            self.oled.text(
                f"mean hr: {hrv_calcs["analysis"]["mean_hr_bpm"]:.01f}", 0, 28, 1
            )
            self.oled.text(f"rmssd: {hrv_calcs["analysis"]["rmssd_ms"]:.01f}", 0, 36, 1)
            self.oled.text(f"sdnn: {hrv_calcs["analysis"]["sdnn_ms"]:.01f}", 0, 44, 1)

        self.selected_row = -1
        self.selector(-1, 0)
        self.oled.show()
        while True:
            # Returns when the knob is pressed
            if self.btn_fifo.has_data():
                self.btn_fifo.get()
                break
