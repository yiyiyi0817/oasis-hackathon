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
# flake8: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timedelta
from typing import Any

from colorama import Back
from yaml import safe_load

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from oasis.clock.clock import Clock
from oasis.social_agent.agents_generator import (gen_control_agents_with_data,
                                                 generate_reddit_agents)
from oasis.social_platform.channel import Channel
from oasis.social_platform.platform import Platform
from oasis.social_platform.typing import ActionType

social_log = logging.getLogger(name="social")
social_log.setLevel("DEBUG")
now = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
file_handler = logging.FileHandler(f"./log/social-{str(now)}.log",
                                   encoding="utf-8")
file_handler.setLevel("DEBUG")
file_handler.setFormatter(
    logging.Formatter("%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
social_log.addHandler(file_handler)
stream_handler = logging.StreamHandler()
stream_handler.setLevel("DEBUG")
stream_handler.setFormatter(
    logging.Formatter("%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
social_log.addHandler(stream_handler)

parser = argparse.ArgumentParser(description="Arguments for script.")
parser.add_argument(
    "--config_path",
    type=str,
    help="Path to the YAML config file.",
    required=False,
    default="",
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "mock_reddit.db")
DEFAULT_USER_PATH = os.path.join(DATA_DIR, "reddit",
                                 "filter_user_results.json")
DEFAULT_PAIR_PATH = os.path.join(DATA_DIR, "reddit", "RS-RC-pairs.json")

ROUND_POST_NUM = 20


async def running(
    db_path: str | None = DEFAULT_DB_PATH,
    user_path: str | None = DEFAULT_USER_PATH,
    pair_path: str | None = DEFAULT_PAIR_PATH,
    round_post_num: str | None = ROUND_POST_NUM,
    num_timesteps: int = 3,
    clock_factor: int = 60,
    recsys_type: str = "reddit",
    controllable_user: bool = True,
    allow_self_rating: bool = False,
    show_score: bool = True,
    max_rec_post_len: int = 20,
    activate_prob: float = 0.1,
    follow_post_agent: bool = False,
    mute_post_agent: bool = True,
    model_configs: dict[str, Any] | None = None,
    inference_configs: dict[str, Any] | None = None,
    refresh_rec_post_count: int = 10,
    user_number: int = 1,
    action_space_file_path: str = None,
) -> None:
    db_path = DEFAULT_DB_PATH if db_path is None else db_path
    user_path = DEFAULT_USER_PATH if user_path is None else user_path
    pair_path = DEFAULT_PAIR_PATH if pair_path is None else pair_path
    if os.path.exists(db_path):
        os.remove(db_path)

    start_time = datetime(2024, 8, 6, 8, 0)
    clock = Clock(k=clock_factor)
    twitter_channel = Channel()
    print(action_space_file_path)
    with open(action_space_file_path, "r", encoding="utf-8") as file:
        action_space_prompt = file.read()
    with open(pair_path, "r") as f:
        pairs = json.load(f)
    infra = Platform(
        db_path,
        twitter_channel,
        clock,
        start_time,
        allow_self_rating=allow_self_rating,
        show_score=show_score,
        recsys_type=recsys_type,
        max_rec_post_len=max_rec_post_len,
        refresh_rec_post_count=refresh_rec_post_count,
    )
    for i in range(len(pairs)):
        await infra.sign_up_product(i+1, pairs[i]["name"])

    inference_channel = Channel()

    twitter_task = asyncio.create_task(infra.running())

    if inference_configs["model_type"][:3] == "gpt":
        is_openai_model = True
    if not controllable_user:
        raise ValueError("Uncontrollable user is not supported")
    else:
        agent_graph, id_mapping = await gen_control_agents_with_data(
            twitter_channel,
            1,
        )
        agent_graph = await generate_reddit_agents(
            user_number,
            user_path,
            twitter_channel,
            inference_channel,
            agent_graph,
            id_mapping,
            follow_post_agent,
            mute_post_agent,
            action_space_prompt,
            inference_configs["model_type"],
            is_openai_model,
        )

    for timestep in range(num_timesteps):
        os.environ["TIME_STAMP"] = str(timestep + 1)
        if timestep == 0:
            start_time_0 = datetime.now()
        print(Back.GREEN + f"timestep:{timestep}" + Back.RESET)
        social_log.info(f"timestep:{timestep + 1}.")

        post_agent = agent_graph.get_agent(0)
        if timestep == 0:
            for i in range(len(pairs)):
                product_content = f"Product name: '{pairs[i]['name']}'. {pairs[i]['content']}"
                await post_agent.perform_action_by_data(
                    "create_post", content=product_content)

        await infra.update_rec_table()
        social_log.info("update rec table.")
        tasks = []
        for _, agent in agent_graph.get_agents():
            if agent.user_info.is_controllable is False:
                if random.random() < activate_prob:
                    tasks.append(agent.perform_action_by_llm())
        random.shuffle(tasks)
        await asyncio.gather(*tasks)

        if timestep == 0:
            time_difference = datetime.now() - start_time_0

            # Convert two hours into seconds since time_difference is a
            # timedelta object
            two_hours_in_seconds = timedelta(hours=2).total_seconds()

            # Calculate two hours divided by the time difference (in seconds)
            clock_factor = two_hours_in_seconds / \
                time_difference.total_seconds()
            clock.k = clock_factor
            social_log.info(f"clock_factor: {clock_factor}")

    await twitter_channel.write_to_receive_queue((None, None, ActionType.EXIT))

    await twitter_task

    social_log.info("Simulation finish!")


if __name__ == "__main__":
    args = parser.parse_args()

    if os.path.exists(args.config_path):
        with open(args.config_path, "r") as f:
            cfg = safe_load(f)
        data_params = cfg.get("data")
        simulation_params = cfg.get("simulation")
        model_configs = cfg.get("model")
        inference_params = cfg.get("inference")
        asyncio.run(
            running(
                **data_params,
                **simulation_params,
                model_configs=model_configs,
                inference_configs=inference_params,
            ),
            debug=True,
        )
    else:
        asyncio.run(running())
