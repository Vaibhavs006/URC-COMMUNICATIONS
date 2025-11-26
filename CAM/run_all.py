import subprocess
import sys
import time
import signal
import os

def run_webcams():
    """
    Run all three webcam WebSocket servers simultaneously
    """
    print("=" * 60)
    print("Starting all webcam WebSocket servers...")
    print("=" * 60)
    print("\nServers will run on:")
    print("  Camera 1: ws://0.0.0.0:8765")
    print("  Camera 2: ws://0.0.0.0:8766")
    print("  Camera 3: ws://0.0.0.0:8767")
    print("\nPress Ctrl+C to stop all servers")
    print("=" * 60)
    print()
    
    # List of webcam scripts to run
    scripts = ['webcam1.py', 'webcam2.py', 'webcam3.py']
    
    # List to store process objects
    processes = []
    
    def signal_handler(sig, frame):
        """Handle Ctrl+C gracefully"""
        print("\n\n" + "=" * 60)
        print("Shutting down all webcam servers...")
        print("=" * 60)
        
        for i, process in enumerate(processes, 1):
            if process.poll() is None:
                print(f"Stopping Camera {i}...")
                process.terminate()
        
        # Wait for all processes to terminate
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        print("\nAll webcam servers stopped successfully.")
        sys.exit(0)
    
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Start each webcam script as a separate process
        for i, script in enumerate(scripts, 1):
            print(f"Launching Camera {i} ({script})...")
            
            # Use subprocess.Popen to run scripts in parallel
            if sys.platform == "win32":
                # Windows
                process = subprocess.Popen(
                    [sys.executable, script],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                # Linux/Mac
                process = subprocess.Popen([sys.executable, script])
            
            processes.append(process)
            time.sleep(1)  # Small delay between launches
        
        print("\n" + "=" * 60)
        print("All webcam servers launched successfully!")
        print("=" * 60)
        print("\nServers are running. Monitor the output above.")
        print("Press Ctrl+C to stop all servers.\n")
        
        # Keep the script running and monitor processes
        while True:
            time.sleep(1)
            
            # Check if any process has terminated unexpectedly
            for i, process in enumerate(processes, 1):
                if process.poll() is not None:
                    print(f"\nWarning: Camera {i} process terminated unexpectedly!")
                    
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        
        # Terminate all processes in case of error
        for process in processes:
            if process.poll() is None:
                process.terminate()
        
        for process in processes:
            process.wait()

if __name__ == "__main__":
    run_webcams()
