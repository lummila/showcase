import json


class History:
    def __init__(self):
        self.output = {}
        self.number_of_lines = 0
        self.file = "History_file.txt"

    def store_data(self, data: str):
        new_data = data + "\n"
        # Read data and find out how much stuff is in it. Find out the number of lines
        with open(self.file) as created_file:
            self.number_of_lines = len(created_file.readlines())
        # If the number of lines is smaller than four, we can simply add the text
        if self.number_of_lines < 4:
            with open(self.file, "a") as created_file:
                created_file.write(new_data)
        else:
            # If the four history slots are already full,
            # we have to drop the first one and write to the file:
            with open(self.file) as created_file:
                # Read first line but don't save it
                created_file.readline()
                # Create conten instance and save the data there
                content = ""
                for i in range(3):
                    content += created_file.readline()
                content += new_data
                # Write the data
            with open(self.file, "w") as created_file:
                created_file.write(content)
            print("History store to file completed")

    # Returns a dictionary with every measurement in the .txt file
    def make_dictionary(self):
        with open(self.file, "a") as created_file:
            # First check the current length of the file
            self.number_of_lines = len(created_file.readlines())
            # We read out the line
        with open(self.file) as created_file:
            for i in range(self.number_of_lines):
                line = created_file.readline()
                # Strip off newlines
                line = line.rstrip("\n")
                # Make the string and add into a dictionary
                line = json.loads(line)
                self.output[i + 1] = line
        return self.output


# Example Kubios API call return JSON string
"""test = History(json.dumps({'test':{'test1':0.0, 'testlevel':0.129}}))
test=History(json.dumps({'analysis': {'artefact': 0.0, 'artefact_level': 'GOOD', 'create_timestamp': '2024-04-30T10:57:28.399506+00:00',
                     'freq_domain': {'HF_peak': 0.19666666666666666, 'HF_power': 643.8597348835933,
                                     'HF_power_nu': 78.43759995255542, 'HF_power_prc': 76.93377727768024,
                                     'LF_HF_power': 0.2730351722246044, 'LF_peak': 0.15, 'LF_power': 175.79635360243,
                                     'LF_power_nu': 21.416223611930583, 'LF_power_prc': 21.005627128900773,
                                     'VLF_peak': 0.04, 'VLF_power': 16.0452520206049,
                                     'VLF_power_prc': 1.9172216842238836, 'tot_power': 836.9012385284087},
                     'mean_hr_bpm': 74.53416149068323, 'mean_rr_ms': 805.0, 'pns_index': -0.3011304704001718,
                     'readiness': 62.5, 'respiratory_rate': None, 'rmssd_ms': 42.905163398997125,
                     'sd1_ms': 31.170430346875026, 'sd2_ms': 31.704701694991602, 'sdnn_ms': 30.655320818448132,
                     'sns_index': 1.767118595291916, 'stress_index': 18.454910359256793}, 'status': 'ok'}))
                     
test.get_data()
test.read_history()
test.make_dictionary()"""
