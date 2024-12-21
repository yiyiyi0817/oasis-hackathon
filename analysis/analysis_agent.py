# ========= Copyright 2023-2024 @ CAMEL-AI.org. All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2023-2024 @ CAMEL-AI.org. All Rights Reserved. =========
from colorama import Fore
from fpdf import FPDF
import os
import sqlite3

from camel.societies import RolePlaying
from camel.utils import print_text_animated
from typing import List


def db_to_str(db_path: str, table_name: str) -> str:
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)

    # Create a cursor object
    cur = conn.cursor()

    # Execute the query
    cur.execute(f"SELECT * FROM {table_name}")

    # Get the names of the columns
    columns = [description[0] for description in cur.description]

    # Fetch all rows
    rows = cur.fetchall()

    result = ""
    for row in rows:
        # Append each row to the result string
        row_str = ', '.join([f'{col}: {value}' for col, value in zip(columns, row)])
        result += row_str + "\n"

    # Close the connection
    conn.close()

    return result


def main(db_lst: List[str], product_text_lst: List[str], goal: str = "提升购买量",
         model=None, chat_turn_limit=5) -> None:
    # 创建输出目录
    output_dir = "marketing_analysis"
    os.makedirs(output_dir, exist_ok=True)

    # 为每个文案创建单独的文本文件
    analysis_files = []
    for i, (db_path, product_text) in enumerate(zip(db_lst, product_text_lst)):
        txt_file = os.path.join(output_dir, f"analysis_{i+1}.md")  # 修改为Markdown文件
        with open(txt_file, "w", encoding="utf-8") as f:
            # 写入文案内容
            f.write(f"# 营销文案 {i+1}\n\n")
            f.write(product_text + "\n\n")

            # 写入数据库分析
            f.write("## 交互结果分析\n")
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for table_name in ['post', 'comment', 'product']:
                cur.execute(f"SELECT * FROM {table_name}")
                columns = [description[0] for description in cur.description]
                rows = cur.fetchall()

                # 使用Markdown表格格式
                f.write(f"\n### {table_name.upper()} 表\n")
                if columns:
                    header = '| ' + ' | '.join(columns) + ' |\n'
                    separator = '| ' + ' | '.join(['---'] * len(columns)) + ' |\n'
                    f.write(header + separator)
                    for row in rows:
                        row_str = '| ' + ' | '.join(map(str, row)) + ' |\n'
                        f.write(row_str)
            conn.close()

        analysis_files.append(txt_file)

    post_str_lst, comment_str_lst, product_str_lst = [], [], []
    for db_path in db_lst:
        post_str_lst.append(db_to_str(db_path, 'post'))
        comment_str_lst.append(db_to_str(db_path, 'comment'))
        product_str_lst.append(db_to_str(db_path, 'product'))


    task_prompt2 = "\n我希望对这个商品做营销文案的传播效果评估，使得能够达到决策目标："
    tips = "请从原始帖子传播的深度、广度、规模，最终获得的点赞数、点踩数等各个方面来分析，特别要注意product表最终的下单量sales来分析。并且列各个小标题形成完整的市场营销报告，且给出一些改进建议的新文案，注意给出的建议要英文的，但是报告的语言用中文。"

    # 先创建 task_prompt1
    task_prompt1 = "我是一个国内的商家，希望商品在海外销售，因此我在国外的社交媒体上发布了几个宣传文案，在对这个商品做营销文案的宣传效果评估。"

    # 生成每个文案的内容，并合并到 task_prompt
    full_task_prompt = task_prompt1  # 初始化任务提示

    for i, product_text in enumerate(product_text_lst):
        # 创建动态的 data_text
        post_str = post_str_lst[i]
        comment_str = comment_str_lst[i]
        product_str = product_str_lst[i]

        data_text = f"""在交互之后，这个文案获得的反馈是
        社交媒体的帖子都有: {post_str}
        社交媒体对这些帖子的评论都有: {comment_str}
        最终的产品销量是: {product_str}
        """

        # 动态生成每个文案的部分
        product_text_with_number = f"我的第{i + 1}个文案是\n" + product_text

        # 合并每个文案的信息
        full_task_prompt += product_text_with_number + data_text

    # 合并剩余的部分
    full_task_prompt += task_prompt2 + goal + tips

    role_play_session = RolePlaying(
        assistant_role_name="市场营销专家",
        assistant_agent_kwargs=dict(model=model),
        user_role_name="商家",
        user_agent_kwargs=dict(model=model),
        task_prompt=full_task_prompt,
        with_task_specify=True,
        task_specify_agent_kwargs=dict(model=model),
        output_language="中文"
    )

    print(
        Fore.GREEN
        + f"AI Assistant sys message:\n{role_play_session.assistant_sys_msg}\n"
    )
    print(
        Fore.BLUE + f"AI User sys message:\n{role_play_session.user_sys_msg}\n"
    )

    print(Fore.YELLOW + f"Original task prompt:\n{full_task_prompt}\n")
    print(
        Fore.CYAN
        + "Specified task prompt:"
        + f"\n{role_play_session.specified_task_prompt}\n"
    )
    print(Fore.RED + f"Final task prompt:\n{role_play_session.task_prompt}\n")

    n = 0
    input_msg = role_play_session.init_chat()
    while n < chat_turn_limit:
        n += 1
        assistant_response, user_response = role_play_session.step(input_msg)

        if assistant_response.terminated:
            print(
                Fore.GREEN
                + (
                    "AI Assistant terminated. Reason: "
                    f"{assistant_response.info['termination_reasons']}."
                )
            )
            break
        if user_response.terminated:
            print(
                Fore.GREEN
                + (
                    "AI User terminated. "
                    f"Reason: {user_response.info['termination_reasons']}."
                )
            )
            break

        print_text_animated(
            Fore.BLUE + f"AI User:\n\n{user_response.msg.content}\n",
            delay=0.0002
        )
        print_text_animated(
            Fore.GREEN + "AI Assistant:\n\n"
            f"{assistant_response.msg.content}\n",
            delay=0.0002
        )

        if "CAMEL_TASK_DONE" in user_response.msg.content:
            break

        input_msg = assistant_response.msg
        for txt_file in analysis_files:
            with open(txt_file, "a", encoding="utf-8") as f:
                f.write("\n## 智能营销分析建议\n\n")
                while n < chat_turn_limit:
                    n += 1
                    assistant_response, user_response = role_play_session.step(input_msg)
                    
                    # 写入对话内容而不是打印
                    f.write(f"### 用户反馈\n{user_response.msg.content}\n\n")
                    f.write(f"### 营销专家建议\n{assistant_response.msg.content}\n\n")

                    if "CAMEL_TASK_DONE" in user_response.msg.content:
                        break
                    input_msg = assistant_response.msg


if __name__ == "__main__":
    db_lst = [
        'emall_hackathon1.db',
        'emall_hackathon2.db',
    ]
    product_text_lst = [
        '🌍 Calling all innovators! Join us in **London** for an **epic Multi-Agent Hackathon** 🧑‍💻🤖. Push the boundaries of AI, collaborate with top minds, and build groundbreaking simulations. 🚀',
        '🚨 **AI enthusiasts in London!** 🚨  Dive into the world of **Multi-Agent Systems** at our Hackathon 🛠✨. Brainstorm, code, and compete to create next-gen simulations 🌐🔥. 👥 Collaborate, win prizes, and make connections!  ',
    ]
    main(db_lst, product_text_lst, goal="提升购买量")
