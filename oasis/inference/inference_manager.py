# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
import asyncio
import logging
import threading

from oasis.inference.inference_thread import InferenceThread, SharedMemory

inference_log = logging.getLogger(name="inference")
inference_log.setLevel("DEBUG")

file_handler = logging.FileHandler("inference.log")
file_handler.setLevel("DEBUG")
file_handler.setFormatter(
    logging.Formatter("%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
inference_log.addHandler(file_handler)


class InferencerManager:
    r"""InferencerManager class to manage multiple inference threads."""

    def __init__(
        self,
        channel,
        model_type,
        model_path,
        stop_tokens,
        server_url,
    ):
        self.count = 0
        self.channel = channel
        self.threads = []
        self.lock = threading.Lock(
        )  # Use thread lock to protect shared resources
        self.stop_event = threading.Event()  # Event for stopping threads
        for url in server_url:
            host = url["host"]
            for port in url["ports"]:
                _url = f"http://{host}:{port}/v1"
                shared_memory = SharedMemory()
                thread = InferenceThread(
                    model_path=model_path,
                    server_url=_url,
                    stop_tokens=stop_tokens,
                    model_type=model_type,
                    temperature=0.0,
                    shared_memory=shared_memory,
                )
                self.threads.append(thread)

    async def run(self):
        # Start threads
        for thread in self.threads:
            thread_ = threading.Thread(target=thread.run)
            thread_.start()

        try:
            while not self.stop_event.is_set():
                for thread in self.threads:
                    # Use thread lock to protect shared state access
                    with self.lock:
                        if thread.shared_memory.Done:
                            await self.channel.send_to(
                                (thread.shared_memory.Message_ID,
                                 thread.shared_memory.Response))
                            thread.shared_memory.Done = False
                            thread.shared_memory.Busy = False
                            thread.shared_memory.Working = False

                    # Check if thread is busy
                    if not thread.shared_memory.Busy:
                        if self.channel.receive_queue.empty():
                            continue

                        # Get new message if thread is idle
                        message = await self.channel.receive_from()
                        # Protect shared state update with lock
                        with self.lock:
                            thread.shared_memory.Message_ID = message[0]
                            thread.shared_memory.Message = message[1]
                            thread.shared_memory.Busy = True
                            self.count += 1
                            inference_log.info(
                                f"Message {self.count} received")

                # Add a reasonable sleep to avoid CPU overload
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            inference_log.info("Inference manager run task cancelled.")
        finally:
            # Clean up threads before stopping
            await self.stop()

    async def stop(self):
        for thread in self.threads:
            thread.alive = False
