from input_control import Screen
from piotimer import Piotimer
from filefifo import Filefifo
from fifo import Fifo
import network
import urequests as requests
import time
import json
import math

# from time import sleep_ms
import framebuf

# import the icons
import heart_27_26
import smiley
import crying26_26

"""
NOTE: QUICK CHEATSHEET FOR FUNCTION FLOW:
Heart rate detection:
 - .heart_rate_detection() gets value from:
  - .operate(), which gets calculated ADC values until sufficient ones activate:
   - .slope_detection(), which returns an PP interval if the measurement was a success.
 - .heart_rate_detection() adds this value to PP interval list, then gets an averaged BPM from:
  - .pulse(), which receives a list of PP intervals and the amount of averaging, returns int(BPM)
 - .heart_rate_detection() adds this to a sum, which is then divided by the amount of BPM in the sum
 - This evaluates a BPM to display on the screen. No returns to make sure it keeps looping.
 - The function ends, once the rotary knob has been pressed.

PP interval detection (The variables are named RR, this was before Aleksi found out they are different things.)
 - .rr_interval_detection() builds an empty list, then loops:
  - .operate(), which loops ADC values until an expression is filled, triggering:
   - .slope_detection(), which returns an RR interval, if successful.
 - .rr_interval_detection() then multiplies that by 1000, and adds it to the list
 - Once the list has 30 items, it removes the first one in it, and returns it.
"""


# Home for heart rate measurement and RR interval gathering
class Measure(Screen):
    def __init__(self) -> None:
        # .oled is still going to be the hub for everything display-related
        Screen.__init__(self)

        # This determines whether the program uses test data or real data
        self.test_mode = False

        # If the values are coming from pulse sensor
        if self.test_mode:
            # Create a filefifo from sample values
            self.measure_test_files = Filefifo(size=100, name="capture01_250Hz.txt")

        #######################################################
        # Max size of five integers, values gotten from file or sensor
        self.normalizing_values = []
        # Sample amount per calculation
        self.samples = 0
        ## Averaging the BPM
        self.prev_beat = 0
        # Current BPM
        self.current_bpm = 0
        # The average of received values
        self.measure_average = 0
        self.min_val = 0
        self.max_val = 0
        #######################################################
        # ECG variables
        self.ecg_fifo = Fifo(500)
        self.ecg_average = 0
        self.ecg_count = 0
        self.ecg_x_index = 0
        self.ecg_y_index = 0

    # Interrupt handler for timer, whether this is active is decided below
    def pio_handler(self, var):
        self.adc_fifo.put(self.adc.read_u16())

    # Get values from self.adc_fifo
    def adc_get(self):
        output = 0
        value = 0

        avg_amount = 20

        # Ends when a valid value is entered to output
        while output == 0:
            # In case the user presses knob, exiting
            while self.btn_fifo.has_data():
                self.btn_fifo.get()
                return -1

            # Test files for debugging reasons
            if self.test_mode:
                while self.measure_test_files.has_data():
                    value = self.measure_test_files.get()
                    if 10_000 < value < 60_000:
                        self.samples += 1
                        output = value
                        break
            # Using live data
            else:
                while self.adc_fifo.has_data():
                    value = self.adc_fifo.get()
                    if 10_000 < value < 60_000:
                        self.samples += 1
                        output = value
                        break

        previous = len(self.normalizing_values)
        """
        If the list of 10 previous normalized values goes over,
        pop the last one
        Otherwise just add the new value to the list
        """
        if previous >= avg_amount:
            self.normalizing_values.pop(0)
        self.normalizing_values.append(output)

        # The output becomes (all values / list length + new value)
        output = int(sum(self.normalizing_values) / (previous + 1))

        # ECG stuff, every 10 outputs is put to ECG fifo for displaying
        self.ecg_average += output
        self.ecg_count += 1
        if self.ecg_count >= 10:
            self.ecg_fifo.put(int(self.ecg_average / self.ecg_count))
            self.ecg_average = 0
            self.ecg_count = 0

        return output

    # Get the average of approx. two seconds' worth of valid values
    def measure_avg(self):
        limit = 500
        value = 0
        total = 0

        # Upper and lower limits for ECG
        self.min_val = self.adc_get()
        self.max_val = self.adc_get()

        for _ in range(limit):
            value = self.adc_get()

            # User has pressed the knob
            if self.min_val == -1 or self.max_val == -1 or value == -1:
                return -1

            self.min_val = value if value < self.min_val else self.min_val
            self.max_val = value if value > self.max_val else self.max_val

            total += value

        output = int(total / limit)
        self.samples = 0
        return output

    def slope_detection(self):
        # Counting every sample for RR interval
        # Rising tracks the direction of the slope
        rising = 0
        self.samples = 0

        while True:
            # Check if ECG can draw
            self.ecg_draw()

            # Get two points for direction of the slope
            value = self.adc_get()
            next_value = self.adc_get()

            if value == -1 or next_value == -1:
                return -1.0

            # In case the beat fails to be captured due to intereference
            if self.samples > 500:
                print("Missed a beat!")
                self.measure_average = self.measure_avg()
                # User has pressed the knob
                if self.measure_average == -1:
                    return -1.0
                self.samples = 0

            # Going up, both values are above average
            #      /
            # ------------
            #   /
            if rising == 0 and value < next_value and self.measure_average < value:
                rising = 1

            # Going down, next value is smaller and both are below threshold
            #   \
            # ------------
            #    \
            if (
                rising == 1
                and next_value < value
                and value < int(self.measure_average * 0.95)
            ):
                rising = 2

            # Going up, and reaching the average
            #      /
            # ------------
            #   /
            if rising == 2 and value < next_value and self.measure_average < next_value:
                # RR INTERVAL MEASUREMENT
                output = float(self.samples / 250)
                self.samples = 0

                # Output is an RR interval in whole seconds
                return output

    # The overall operation for getting an RR interval
    def operate(self):
        while True:
            if self.measure_average == 0:
                self.measure_average = self.measure_avg()

            # Check if ECG can draw
            self.ecg_draw()

            # Get two points for direction of the slope
            value = self.adc_get()
            next_value = self.adc_get()

            # Upholding the min and max values for ECG
            self.min_val = value if value < self.min_val else self.min_val
            self.max_val = value if value > self.max_val else self.max_val

            # If the program goes three seconds without getting a pulse
            if self.samples > 750:
                print("Readjusting")
                self.measure_average = self.measure_avg()
                self.samples = 0

            # Former value is below latter and it's coming from below
            if value < next_value and self.measure_average < next_value:
                # print("Measuring")
                # Return the RR interval in seconds
                output = float(self.slope_detection())
                # User pressed the knob
                if output == -1.0:
                    return -1.0
                return output

    # Beats / intervals added up = seconds per beat times 60
    def pulse(self, rr_list, limit):
        """
        Limit: The amount of interval values to use to normalize the bpm
        Interval_amount: Length of interval list or "limit" if it goes over it
        Interval_value: Sum of "limit" or "interval_amount" amount of values
        """
        interval_amount = len(rr_list) if len(rr_list) < limit else limit
        interval_value = 0

        for x in range(interval_amount):
            interval_value += rr_list[-(1 + x)]

        bpm = int(interval_amount / interval_value * 60)

        # Safeguard for funky values
        if 240 < bpm:
            self.measure_average = self.measure_avg()
            return 0

        output = (self.prev_beat + bpm) / 2
        self.prev_beat = bpm

        return int(output)

    # Will be changed to display on screen, now only prints .pulse()
    def heart_rate_detection(self):
        # Empty the screen and put a placeholder text
        self.oled.fill(0)
        self.add_text("Calculating...", 50, 2)
        self.add_text("Press to return", 50, 3)
        self.oled.show()

        # Turn on the Piotimer
        self.measure_timer = Piotimer(freq=250, callback=self.pio_handler)

        # n latest BPM values, amount is the max length for it
        restricted_interval_list = []
        amount = 3

        pulses = 0
        count = 0

        while True:
            value = self.operate()

            # User pressed the knob, return to main.py
            if value == -1.0:
                self.ecg_reset()
                self.measure_timer.deinit()
                # Empty the fifo
                while self.adc_fifo.has_data():
                    self.adc_fifo.get()
                return
            else:
                restricted_interval_list.append(value)

            # Keep the list size in check
            if len(restricted_interval_list) >= amount:
                restricted_interval_list.pop(0)

            if len(restricted_interval_list) > 0:
                pulses += self.pulse(restricted_interval_list, amount)
                count += 1

            if count >= amount:
                # Average the collected pulse over set amount
                display_pulse = int(pulses / amount)
                count = 0
                pulses = 0

                # Redraw a set section of the screen
                self.oled.fill_rect(0, 33, 128, 15, 0)
                self.add_text(str(display_pulse) + " BPM", 50, 2)
                self.oled.show()

    # Gets RR intervals, add them to the list then returns the list of 29 values
    def rr_interval_detection(self):
        interval_list = []
        # Amount of intervals
        countdown = 30

        # Empty the screen and put a placeholder text
        self.oled.fill(0)
        self.add_text(f"{countdown} left", 50, 2)
        self.add_text("Press to return", 50, 3)
        self.oled.show()

        # Turn on the Piotimer
        self.measure_timer = Piotimer(freq=250, callback=self.pio_handler)

        while len(interval_list) <= 30:
            interval = self.operate()

            if interval == -1.0:
                self.ecg_reset()
                self.measure_timer.deinit()
                # Empty the fifo
                while self.adc_fifo.has_data():
                    self.adc_fifo.get()
                return []
            else:
                value = int(interval * 1000)
                # This means a pulse of over 240
                if value <= 250:
                    continue
                interval_list.append(int(interval * 1000))

            # Display the progress
            self.oled.fill_rect(0, 33, 128, 15, 0)
            self.add_text(f"{countdown} left", 50, 2)
            self.oled.show()
            countdown -= 1

        # The first value is often yucky
        interval_list.pop(0)

        self.ecg_reset()
        self.measure_timer.deinit()
        # Empty the fifo
        while self.adc_fifo.has_data():
            self.adc_fifo.get()

        print(interval_list)
        return interval_list

    def local_hrv(self, rr_intervals: list):
        output = {
            "analysis": {
                "mean_rr_ms": 0.0,
                "mean_hr_bpm": 0.0,
                "rmssd_ms": 0.0,
                "sdnn_ms": 0.0,
            }
        }
        length = len(rr_intervals)

        # Mean of PP interval values (named rr because Kubios JSON)
        mean_rr = sum(rr_intervals) / length
        output["analysis"]["mean_rr_ms"] = mean_rr

        # Mean of beats per minute
        mean_bpm = 0.0
        for interval in rr_intervals:
            mean_bpm += 1 / (interval / 1000) * 60
        output["analysis"]["mean_hr_bpm"] = mean_bpm / length

        # Square root of mean squared differences between successive PP intervals
        rmssd = 0.0
        for x in range(length - 1):
            rmssd += pow(rr_intervals[x + 1] - rr_intervals[x], 2)
        output["analysis"]["rmssd_ms"] = math.sqrt(1 / (length - 1) * rmssd)

        # Standard deviation of PP intervals
        sdnn = 0.0
        for interval in rr_intervals:
            sdnn += pow(interval - mean_rr, 2)
        output["analysis"]["sdnn_ms"] = math.sqrt(1 / length * sdnn)

        return output

    # 0-30 pixels high and 128 wide ECG print
    def ecg_draw(self):
        while self.ecg_fifo.has_data():
            value = self.ecg_fifo.get()
            # Adjust received value for half the screen
            value = int((value - self.min_val) / (self.max_val - self.min_val) * 30)

            # The calculated value goes beyond boundaries, forget about it
            if not 0 <= value <= 30:
                return

            # If the index is at the beginning or at the end
            if self.ecg_x_index == 0 or self.ecg_x_index == 128:
                self.ecg_x_index = 0

                self.oled.vline(self.ecg_x_index, 0, 33, 0)
                self.oled.vline(self.ecg_x_index + 1, 0, 33, 0)

                self.oled.pixel(self.ecg_x_index, 32 - value, 1)
            # Draw a line from last point to the new one.
            else:
                self.oled.line(
                    self.ecg_x_index,
                    32 - self.ecg_y_index,
                    self.ecg_x_index + 1,
                    32 - value,
                    1,
                )
            # Push the index to the next one and save the y-index
            self.ecg_x_index += 2
            self.ecg_y_index = value
            # Clear the next two lines of plotting from last lines
            self.oled.vline(self.ecg_x_index, 0, 33, 0)
            self.oled.vline(self.ecg_x_index + 1, 0, 33, 0)

            self.oled.show()

    # Reset the ECG plotter and empty the fifo
    def ecg_reset(self):
        self.ecg_x_index = 0
        self.ecg_y_index = 0
        while self.ecg_fifo.has_data():
            self.ecg_fifo.get()


# Here we declare everything regarding the WLAN connection
class Internet(Measure):
    def __init__(self):
        # Initialize Measure
        super().__init__()
        self.SSID = "KMD757_GROUP_3"
        self.PASSWORD = "90IG06P0-MO3500"
        self.BROKER_IP = "192.168.1.254"

        self.wlan = network.WLAN(network.STA_IF)

    # Function to connect to WLAN
    def connect_wlan(self):
        # Connecting to the WLAN

        self.wlan.active(True)
        self.wlan.connect(self.SSID, self.PASSWORD)

        # Counting the connect attempts
        attempt_count = 0

        self.oled.fill(0)
        # Attempt to connect once per second
        while not self.wlan.isconnected():
            self.add_text("Connecting.", 50, 2)
            self.oled.show()
            time.sleep(0.25)
            self.oled.fill(0)
            self.add_text("Connecting..", 50, 2)
            self.oled.show()
            time.sleep(0.25)
            self.oled.fill(0)
            self.add_text("Connecting...", 50, 2)
            self.oled.show()
            time.sleep(0.25)
            self.oled.fill(0)
            attempt_count += 1
            # Admit defeat, return to main menu
            if attempt_count >= 10:
                self.oled.fill(0)
                self.add_text("Connection", 50, 0)
                self.add_text("failed!", 50, 1)
                self.add_text("Returning", 50, 2)
                self.add_text("to main menu", 50, 3)
                self.oled.show()
                return

        # Connection successful
        self.oled.fill(0)
        self.add_text("WLAN connected!", 50, 2)
        self.oled.show()
        time.sleep(1)


class Kubios(Internet):
    def __init__(self):
        # Initialize Internet
        super().__init__()

        self.menu = ["Kubios HRV"]
        self.APIKEY = "OMITTED"
        self.CLIENT_ID = "OMITTED"
        self.CLIENT_SECRET = "OMITTED"
        self.LOGIN_URL = "https://kubioscloud.auth.eu-west-1.amazoncognito.com/login"
        self.TOKEN_URL = (
            "https://kubioscloud.auth.eu-west-1.amazoncognito.com/oauth2/token"
        )
        self.REDIRECT_URL = "https://analysis.kubioscloud.com/v1/portal/login"

    # Do the API calls and return a json string of the result
    def calculate_kubios(self, intervals):
        response = requests.post(
            url=self.TOKEN_URL,
            data="grant_type=client_credentials&client_id={}".format(self.CLIENT_ID),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(self.CLIENT_ID, self.CLIENT_SECRET),
        )

        # The API call failed
        if not response.status_code == 200:
            self.oled.fill(0)
            self.add_text("Kubios Failed", 50, 1)
            self.add_text("Press button to try again", 50, 2)
            self.oled.show()
            time.sleep(3)
            # If the user presses the button during the 3 seconds, reattempt
            if self.btn_fifo.has_data():
                response = requests.post(
                    url=self.TOKEN_URL,
                    data="grant_type=client_credentials&client_id={}".format(
                        self.CLIENT_ID
                    ),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    auth=(self.CLIENT_ID, self.CLIENT_SECRET),
                )
            else:
                return ""

        response = response.json()  # Parse JSON response into a python dictionary
        access_token = response["access_token"]  # Parse access token

        # Create the dataset dictionary HERE
        dataset = {"type": "RRI", "data": intervals, "analysis": {"type": "readiness"}}
        # Make the readiness analysis with the given data
        response = requests.post(
            url="https://analysis.kubioscloud.com/v2/analytics/analyze",
            headers={
                "Authorization": "Bearer {}".format(
                    access_token
                ),  # Use access token toaccess your Kubios Cloud analysis session
                "X-Api-Key": self.APIKEY,
            },
            json=dataset,
        )  # Dataset will be automatically converted to JSON by the urequests library

        response = response.json()

        # Finding the stress and recovery values here
        stress_str = str(round((response["analysis"]["stress_index"])))
        recovery_str = str(round((response["analysis"]["readiness"])))

        # Add the pictures
        # Creating frame buffers for images that must be downloaded to Pico
        image = framebuf.FrameBuffer(heart_27_26.img, 27, 26, framebuf.MONO_VLSB)
        image2 = framebuf.FrameBuffer(smiley.img, 26, 26, framebuf.MONO_VLSB)
        image3 = framebuf.FrameBuffer(crying26_26.img, 26, 26, framebuf.MONO_VLSB)

        self.oled.fill(0)

        self.add_text("Connecting.", 50, 2)
        self.oled.show()
        time.sleep(0.25)
        self.oled.fill(0)
        self.add_text("Connecting..", 50, 2)
        self.oled.show()
        time.sleep(0.25)
        self.oled.fill(0)
        self.add_text("Connecting...", 50, 2)
        self.oled.show()
        time.sleep(0.25)
        self.oled.fill(0)
        time.sleep(0.25)

        # If the stress index is bigger than 12, then we add a crying, otherwise a smiling face
        if round((response["analysis"]["stress_index"])) >= 12:
            print(round((response["analysis"]["stress_index"])))
            self.oled.blit(image, 10, 0)
            self.oled.text("recovery %", 40, 3, 1)
            self.oled.text(recovery_str, 62, 15, 1)
            self.oled.blit(image3, 10, 28)
            self.oled.text("stress index", 42, 34, 1)
            self.oled.text(stress_str, 62, 44, 1)

        else:
            self.oled.blit(image, 10, 0)
            self.oled.text("recovery %", 40, 3, 1)
            self.oled.text(recovery_str, 62, 15, 1)
            self.oled.blit(image2, 10, 28)
            self.oled.text("stress idx.", 42, 34, 1)
            self.oled.text(stress_str, 62, 44, 1)

        self.oled.show()
        # Wait for knob input
        while self.btn_fifo.empty():
            time.sleep(0.1)
        self.btn_fifo.get()

        return json.dumps(response)
