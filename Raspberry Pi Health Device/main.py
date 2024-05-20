from history import History
from operations import Kubios, Internet
import time
import json


"""
Remember that inherited methods and variables are accessible in the
"root" unless stated otherwise (like the .oled having all display
methods).
Remember this with FIFOs!
"""


class Main(Kubios, Internet, History):
    def __init__(self) -> None:
        # History handles writing and reading previous measures to/from data.
        History.__init__(self)

        """
        Operations has:
         - Rotary, Button and Sensor pins:
            - .button and .btn_fifo
            - .rot_a, .rot_b and .rot_fifo
            - .adc and .adc_fifo
         - Screen:
            - .oled has everything important related to display
         - Measure:
            - .pulse and .rr_intervals
              - They both use .slope_detection for algorithm
              - DON'T USE .slope_detection ALONE!
        """
        Kubios.__init__(self)

        """
        WLAN properties are stored in self.wlan for stability reasons.
        Once they're set up, there shouldn't be any reason to mess with them.
        """

        Internet.__init__(self)

        self.update = True

        self.main_menu_text = ["HR measure", "Basic HRV", "Kubios HRV", "History"]

        self.hr_menu_text = ["Calculate HR"]

        self.hrv_menu_text = ["Calculate HRV"]

        self.kubios_menu_text = ["Kubios HRV"]

        self.history_data = {}
        self.history_menu_text = ["- EMPTY -", "- EMPTY -", "- EMPTY -", "- EMPTY -"]
        self.update_history_text()

    # Update History menu titles to updated analyses from file
    def update_history_text(self):
        self.history_data = self.make_dictionary()
        # If there's previous data, replace title "- EMPTY -" with a date from file
        for x in range(4):
            if x + 1 in self.history_data:
                self.history_menu_text[x] = self.date_from_file(
                    self.history_data[x + 1]
                )


main = Main()


#######################################START#################################################
while True:
    # menu select
    if main.update:
        if main.main_menu:
            main.show_content(main.main_menu_text)
            main.update = False
        elif main.hr_menu:
            main.show_content(main.hr_menu_text)
            main.update = False

        elif main.hrv_menu:
            main.show_content(main.hrv_menu_text)
            main.update = False

        elif main.kubios_menu:
            main.show_content(main.kubios_menu_text)
            main.update = False

        elif main.history_menu:
            main.show_content(main.history_menu_text)
            main.update = False

    # Check if knob is rotated
    while main.rot_fifo.has_data():
        direction = main.rot_fifo.get()
        main.selector(direction, main.MENU_ROWS)
        main.update = True

    # Check if button is pressed
    while main.btn_fifo.has_data():
        button_buffer = main.btn_fifo.get()
        if button_buffer == 1:
            # Main menu functions
            if main.main_menu:
                if main.selected_row == 0:
                    main.selected_row = 2
                    main.hr_menu = True
                elif main.selected_row == 1:
                    main.selected_row = 2
                    main.hrv_menu = True
                elif main.selected_row == 2:
                    main.selected_row = 2
                    main.kubios_menu = True
                elif main.selected_row == 3:
                    main.selected_row = 0
                    main.history_menu = True
                main.main_menu = False
                main.update = True

            # Heart rate menu functions
            elif main.hr_menu:
                # Only if the cursor is pressed on menu option, activate HR
                # measurement, anything else => main menu
                if main.selected_row == 2:
                    print("HR measure")
                    # The process ends when knob is pressed
                    main.heart_rate_detection()
                    print("HR measurement done")
                main.main_menu = True
                main.hr_menu = False
                main.selected_row = 0
                main.update = True

            # Basic HRV menu functions
            elif main.hrv_menu:
                if main.selected_row == -1:
                    main.main_menu = True
                    main.selected_row = 1
                elif main.selected_row == 2:
                    print("HRV analysis")
                    rr_measures = main.rr_interval_detection()
                    # Knob was pressed during measurement
                    if len(rr_measures) < 29:
                        main.oled.fill(0)
                        main.add_text("Analysis interrupted.", 50, 1)
                        time.sleep(3)
                        main.kubios_menu = True
                    else:
                        local_hrv_analysis = main.local_hrv(rr_measures)
                        # Display the local HRV analysis
                        main.display_analysis(local_hrv_analysis, False)
                    main.selected_row = 0
                main.main_menu = True
                main.hrv_menu = False
                main.update = True

            # Kubios menu functions
            elif main.kubios_menu:
                if main.selected_row == -1:
                    main.main_menu = True
                    main.selected_row = 2
                elif main.selected_row == 2:
                    # Connect to WLAN for Kubios connection
                    main.connect_wlan()
                    # If internet connection failed
                    if not main.wlan.isconnected():
                        time.sleep(3)
                        main.selected_row = 3
                        main.kubios_menu = False
                        main.main_menu = True
                        main.update = True
                    else:
                        # For debugging
                        """Example_data: [
                            828,
                            836,
                            852,
                            760,
                            800,
                            796,
                            856,
                            824,
                            808,
                            776,
                            724,
                            816,
                            800,
                            812,
                            812,
                            812,
                            756,
                            820,
                            812,
                            800,
                        ]"""

                        rr_measures = main.rr_interval_detection()
                        # rr_interval_detection() was interrupted
                        if len(rr_measures) < 29:
                            main.oled.fill(0)
                            main.add_text("Analysis interrupted.", 50, 2)
                            time.sleep(3)
                            main.kubios_menu = True
                        else:
                            # Make an API call to Kubios
                            main.oled.fill(0)
                            main.add_text("Connecting.", 50, 2)
                            main.oled.show()
                            kubios_measurement = main.calculate_kubios(rr_measures)
                            # API call failed
                            if kubios_measurement == "":
                                main.kubios_menu = False
                                main.main_menu = True
                            else:
                                # Stores Kubios data to history text file
                                main.store_data(kubios_measurement)
                                main.update_history_text()
                                main.kubios_menu = False
                                main.display_analysis(
                                    json.loads(kubios_measurement), True
                                )

                main.kubios_menu = False
                main.main_menu = True
                main.selected_row = 0
                main.update = True

            # History menu functions
            elif main.history_menu:
                # First element, if not empty
                if main.selected_row == 0 and main.history_menu_text[0] != "- EMPTY -":
                    main.display_analysis(main.history_data[1], True)
                    # print("1. History")  # history 1 file
                # Second element
                elif (
                    main.selected_row == 1 and main.history_menu_text[1] != "- EMPTY -"
                ):
                    main.display_analysis(main.history_data[2], True)
                    # print("2. History")  # history 2 file
                # Third element
                elif (
                    main.selected_row == 2 and main.history_menu_text[2] != "- EMPTY -"
                ):
                    main.display_analysis(main.history_data[3], True)
                    # print("3. History")  # history 3 file
                # Fourth element
                elif (
                    main.selected_row == 3 and main.history_menu_text[3] != "- EMPTY -"
                ):
                    main.display_analysis(main.history_data[4], True)
                    # print("4. History")  # history 4 file

                # Go back
                elif main.selected_row == -1:
                    main.main_menu = True
                    main.selected_row = 3
                    main.history_menu = False
                main.update = True
