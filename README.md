# URC-COMMUNICATIONS

This repository contains the communication modules used for transmitting camera feeds between the **rover (Jetson)** and the **base stations**.

## File Descriptions

### RoverUI
- **Purpose:** User Interface for the rover.
- **Runs on:** Base Stations  
- **Description:**  
  Provides the graphical interface used by operators to view camera feeds and control the rover.

---

### sourceCam_color.py
- **Purpose:** Sends color video feed.
- **Runs on:** Jetson (Rover)  
- **Description:**  
  Captures color video from the rover camera and streams it to the base stations.

---

### testpy.py
- **Purpose:** Receives grayscale video feed.
- **Runs on:** Base Stations  
- **Description:**  
  Receives and displays the grayscale video stream sent from the rover.

---

### source_greyscale.py  
*(Named `working.py` on the Jetson)*

- **Purpose:** Sends grayscale video feed.
- **Runs on:** Jetson (Rover)  
- **Description:**  
  Captures grayscale video from the rover camera and streams it to the base stations.

---

## System Overview

Jetson (Rover):
- sourceCam_color.py → Sends color stream  
- working.py → Sends grayscale stream  

Base Station:
- RoverUI → Displays color stream  
- testpy.py → Displays grayscale stream  

---

## Notes
- Ensure rover and base station are on the same network.
- Update IP addresses in scripts before running.
- Run sender scripts on Jetson and receiver/UI scripts on base stations.
