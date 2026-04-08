#!/usr/bin/env python3
"""
ZMK Studio RPC Protocol Probe
Diagnoses connectivity issues with ZMK keyboards via serial port.
"""

import json
import serial
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
import argparse


class ZMKProbe:
    """Probe ZMK keyboard via ZMK Studio RPC protocol"""

    # Standard ZMK serial settings
    BAUD_RATE = 115200
    TIMEOUT = 2.0

    def __init__(self, port: str, verbose: bool = False):
        self.port = port
        self.verbose = verbose
        self.ser: Optional[serial.Serial] = None
        self.message_id = 1

    def log(self, msg: str):
        if self.verbose:
            print(f"[LOG] {msg}")

    def info(self, msg: str):
        print(f"[INFO] {msg}")

    def error(self, msg: str):
        print(f"[ERROR] {msg}")

    def success(self, msg: str):
        print(f"[✓] {msg}")

    def connect(self) -> bool:
        """Attempt to connect to the serial port"""
        try:
            self.log(f"Attempting to open {self.port} at {self.BAUD_RATE} baud")
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.BAUD_RATE,
                timeout=self.TIMEOUT,
                write_timeout=self.TIMEOUT
            )
            self.success(f"Serial port {self.port} opened")
            self.log(f"Serial settings: {self.BAUD_RATE} baud, {self.TIMEOUT}s timeout")
            return True
        except serial.SerialException as e:
            self.error(f"Failed to open {self.port}: {e}")
            return False

    def disconnect(self):
        """Close the serial port"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.log("Serial port closed")

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """Send a JSON-RPC 2.0 request"""
        if not self.ser or not self.ser.is_open:
            self.error("Serial port not open")
            return False

        request = {
            "jsonrpc": "2.0",
            "id": self.message_id,
            "method": method,
        }
        if params:
            request["params"] = params

        self.message_id += 1

        msg = json.dumps(request) + "\n"
        self.log(f"Sending: {msg.strip()}")

        try:
            self.ser.write(msg.encode())
            return True
        except serial.SerialException as e:
            self.error(f"Failed to send request: {e}")
            return False

    def read_response(self, timeout: Optional[float] = None) -> Optional[Dict]:
        """Read a JSON-RPC response"""
        if not self.ser:
            return None

        old_timeout = self.ser.timeout
        if timeout:
            self.ser.timeout = timeout

        try:
            line = self.ser.readline()
            if not line:
                self.log("No response (timeout)")
                return None

            response_str = line.decode('utf-8', errors='replace').strip()
            self.log(f"Received: {response_str}")

            if not response_str:
                return None

            response = json.loads(response_str)
            return response
        except json.JSONDecodeError as e:
            self.error(f"Invalid JSON in response: {e}")
            self.log(f"Raw response: {line}")
            return None
        except Exception as e:
            self.error(f"Error reading response: {e}")
            return None
        finally:
            self.ser.timeout = old_timeout

    def probe_keyboard_info(self) -> Optional[Dict]:
        """Query keyboard info"""
        self.info("Probing keyboard info...")
        if not self.send_request("get_keyboard_info"):
            return None

        response = self.read_response()
        if response:
            if "error" in response:
                self.error(f"RPC error: {response['error']}")
                return None
            if "result" in response:
                self.success(f"Got keyboard info: {response['result']}")
                return response['result']

        return None

    def probe_version(self) -> Optional[str]:
        """Query version info"""
        self.info("Probing version...")
        if not self.send_request("version"):
            return None

        response = self.read_response()
        if response:
            if "error" in response:
                self.log(f"RPC error: {response['error']}")
                return None
            if "result" in response:
                version = response['result']
                self.success(f"Got version: {version}")
                return version

        return None

    def probe_hello(self) -> Optional[Dict]:
        """Send a hello/ping message"""
        self.info("Sending hello message...")
        if not self.send_request("hello"):
            return None

        response = self.read_response()
        if response:
            if "error" in response:
                self.log(f"RPC error: {response['error']}")
                return None
            if "result" in response:
                self.success(f"Hello response: {response['result']}")
                return response['result']

        return None

    def probe_generic(self, method: str) -> Optional[Dict]:
        """Send a generic RPC request"""
        self.info(f"Trying RPC method: {method}...")
        if not self.send_request(method):
            return None

        response = self.read_response()
        if response:
            if "error" in response:
                self.log(f"RPC error: {response['error'].get('message', 'unknown')}")
                return None
            if "result" in response:
                self.success(f"Method {method} succeeded: {response['result']}")
                return response['result']

        return None

    def check_serial_data(self) -> bool:
        """Check if keyboard is sending any data"""
        self.info("Checking for incoming data (5 second window)...")
        if not self.ser or not self.ser.is_open:
            return False

        self.ser.timeout = 0.5
        start = time.time()
        data_received = False

        while time.time() - start < 5:
            try:
                line = self.ser.readline()
                if line:
                    data_received = True
                    msg = line.decode('utf-8', errors='replace').strip()
                    self.log(f"Incoming: {msg}")
            except Exception as e:
                self.error(f"Error reading: {e}")

        self.ser.timeout = self.TIMEOUT

        if data_received:
            self.success("Keyboard is sending data")
        else:
            self.error("No data received from keyboard")

        return data_received

    def run_diagnostics(self):
        """Run full diagnostics"""
        self.info(f"=== ZMK Studio RPC Probe ===")
        self.info(f"Port: {self.port}")
        self.info(f"Baud: {self.BAUD_RATE}")
        self.info("")

        if not self.connect():
            return False

        try:
            # Try to read any existing data first
            self.check_serial_data()
            self.info("")

            # Try different RPC methods
            methods_to_try = [
                ("hello", {}),
                ("version", {}),
                ("get_keyboard_info", {}),
                ("info", {}),
            ]

            success_count = 0
            for method, params in methods_to_try:
                if self.send_request(method, params if params else None):
                    response = self.read_response()
                    if response and ("result" in response or "error" in response):
                        if "result" in response:
                            self.success(f"{method}: OK")
                            success_count += 1
                            if response['result']:
                                self.log(f"  Result: {response['result']}")
                        else:
                            error_msg = response["error"]
                            if isinstance(error_msg, dict):
                                self.error(f"{method}: {error_msg.get('message', 'unknown error')}")
                            else:
                                self.error(f"{method}: {error_msg}")
                time.sleep(0.2)

            self.info("")
            self.info(f"Summary: {success_count}/{len(methods_to_try)} methods responded")

            if success_count > 0:
                self.success("Keyboard is responding to RPC protocol!")
                return True
            else:
                self.error("Keyboard did not respond to any RPC methods")
                self.info("\nTroubleshooting steps:")
                self.info("1. Check that the keyboard is properly plugged in (USB)")
                self.info("2. Verify the port is correct (/dev/ttyACM0 or /dev/ttyACM1)")
                self.info("3. Try the other port if available")
                self.info("4. Check keyboard logs: dmesg")
                self.info("5. Verify ZMK firmware is built with RPC support")
                self.info("6. Try reconnecting the USB cable")
                return False

        finally:
            self.disconnect()


def find_zmk_ports() -> list[str]:
    """Find potential ZMK keyboard ports"""
    ports = []
    for i in range(4):
        port = f"/dev/ttyACM{i}"
        if Path(port).exists():
            ports.append(port)

    return ports


def main():
    parser = argparse.ArgumentParser(
        description="Probe ZMK keyboard via ZMK Studio RPC protocol"
    )
    parser.add_argument(
        "-p", "--port",
        help="Serial port (e.g., /dev/ttyACM0)",
        default=None
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "-a", "--auto",
        action="store_true",
        help="Auto-detect and probe all available ACM ports"
    )

    args = parser.parse_args()

    ports_to_probe = []

    if args.port:
        ports_to_probe = [args.port]
    elif args.auto:
        ports_to_probe = find_zmk_ports()
        if not ports_to_probe:
            print("[ERROR] No /dev/ttyACM* ports found")
            return 1
    else:
        # Default: try common ports
        ports_to_probe = ["/dev/ttyACM0", "/dev/ttyACM1"]

    print(f"Probing ports: {ports_to_probe}\n")

    for port in ports_to_probe:
        if not Path(port).exists():
            print(f"[SKIP] {port} does not exist\n")
            continue

        probe = ZMKProbe(port, verbose=args.verbose)
        success = probe.run_diagnostics()
        print()

        if success:
            return 0

    print("[ERROR] Could not connect to keyboard on any port")
    return 1


if __name__ == "__main__":
    sys.exit(main())
