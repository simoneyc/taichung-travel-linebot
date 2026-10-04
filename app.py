from flask import Flask, request, abort
import os
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from urllib.parse import parse_qs, urlencode, urlparse
from functools import lru_cache
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import requests
from bs4 import BeautifulSoup
import random
import re


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')
# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))


# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        abort(400)
    # get request body as text
    body = request.get_data(as_text=True)
    # Webhook bodies contain personal data; never log them.
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except PyMongoError:
        app.logger.warning('Database operation failed')
        abort(503)
    return 'OK'

# 全局變數來保存用戶的區域選擇
user_region = {}
user_category = {}
new_data = {}
user_chat_status = {}
user_mode = {}
user_scores = {}
question_index = {}
user_answers = {}
game_data = {}

# 定義台中市區域列表
taichung_regions = [
    '南區', '北區', '中區', '西區', '東區', '北屯區', '大里區', '烏日區',
    '南屯區', '西屯區', '大雅區', '豐原區', '潭子區'
]

def create_quick_reply_buttons():
    items = [
        QuickReplyButton(action=PostbackAction(label=region, data=f'region={region}'))
        for region in taichung_regions
    ]
    return QuickReply(items=items)

# 連接到 MongoDB Atlas
@lru_cache(maxsize=1)
def get_client():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is required")
    return MongoClient(uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000,
                       socketTimeoutMS=5000)


def get_database(dbname):
    if dbname not in {"美食", "點心", "景點", "遊戲"}:
        raise ValueError("Unsupported database")
    return get_client()[dbname]


# 從資料庫中獲取隨機的項目
def get_random_items_from_db(category, region):
    db = get_database(category)
    if region not in taichung_regions:
        raise ValueError("Unsupported region")
    collection = db[region]
    random_items = collection.aggregate([{'$sample': {'size': 3}}])
    return list(random_items)
    
# 從資料庫中獲取前三高評分的項目
def get_top_rated_items_from_db(category, region):
    db = get_database(category)
    if region not in taichung_regions:
        raise ValueError("Unsupported region")
    collection = db[region]
    top_items = collection.find().sort('Star', -1).limit(3)
    return list(top_items)

def create_flex_message(data, user_id=None):
    if not data:
        return TextSendMessage(text="此區域暫時沒有資料，請試試其他區域。")
    bubbles = []
    for item in data:
        title = str(item.get("Title") or "無標題")[:80]
        phone = item.get("Phone", "無電話")
        address = item.get("Address", "無地址")
        business_hours = item.get("Business Hours", "無營業時間")
        google_maps_link = item.get("Google Maps Link", "https://maps.google.com")
        star = item.get("Star", "0.0")
        image_link = item.get("Image Link", "")
        if not isinstance(image_link, str) or urlparse(image_link).scheme != "https":
            image_link = None

        # 確認電話號碼格式是否有效
        phone_text = TextComponent(text=f"電話：{phone}", wrap=True)
        if isinstance(phone, str) and re.fullmatch(r"\+?[0-9 ()-]{6,25}", phone):
            phone_text = TextComponent(
                text=f"電話：{phone}",
                wrap=True,
                action=URIAction(uri=f"tel:{phone}")
            )

        # 確認 Google Maps Link 是否有效
        if not isinstance(google_maps_link, str) or urlparse(google_maps_link).scheme != "https" or not urlparse(google_maps_link).netloc:
            google_maps_link = "https://maps.google.com"

        bubble = BubbleContainer(
            direction='ltr',
            hero=ImageComponent(
                url=image_link,
                size='full',
                aspect_ratio='16:9',
                aspect_mode='cover'
            ) if image_link else None,
            body=BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text=title, weight='bold', size='lg'),
                    BoxComponent(layout='vertical', margin='lg', spacing='sm', contents=[
                        phone_text,
                        TextComponent(text=f"地址：{address}", wrap=True),
                        TextComponent(text=f"評分：{star}", wrap=True),
                        TextComponent(text=f"營業時間：{business_hours}", wrap=True),
                        ButtonComponent(
                            style='link',
                            height='sm',
                            action=URIAction(label='查看地圖', uri=google_maps_link)
                        ),
                        BoxComponent(
                            layout='horizontal',
                            spacing='sm',
                            contents=[
                                ButtonComponent(
                                    style='primary',
                                    color='#FF0000',
                                    height='sm',
                                    action=PostbackAction(label='1', data=urlencode({'rating': 1, 'title': title, 'category': user_category.get(user_id), 'region': user_region.get(user_id)}))
                                ),
                                ButtonComponent(
                                    style='primary',
                                    color='#FF7F00',
                                    height='sm',
                                    action=PostbackAction(label='2', data=urlencode({'rating': 2, 'title': title, 'category': user_category.get(user_id), 'region': user_region.get(user_id)}))
                                ),
                                ButtonComponent(
                                    style='primary',
                                    color='#FFFF00',
                                    height='sm',
                                    action=PostbackAction(label='3', data=urlencode({'rating': 3, 'title': title, 'category': user_category.get(user_id), 'region': user_region.get(user_id)}))
                                ),
                                ButtonComponent(
                                    style='primary',
                                    color='#7FFF00',
                                    height='sm',
                                    action=PostbackAction(label='4', data=urlencode({'rating': 4, 'title': title, 'category': user_category.get(user_id), 'region': user_region.get(user_id)}))
                                ),
                                ButtonComponent(
                                    style='primary',
                                    color='#00FF00',
                                    height='sm',
                                    action=PostbackAction(label='5', data=urlencode({'rating': 5, 'title': title, 'category': user_category.get(user_id), 'region': user_region.get(user_id)}))
                                )
                            ]
                        )
                    ])
                ]
            )
        )
        bubbles.append(bubble)

    return FlexSendMessage(alt_text="想選嗎都給你選", contents=CarouselContainer(contents=bubbles))

def get_weather_info(region):
    url = f"https://weather.yam.com/{region}/臺中"
    if region not in taichung_regions:
        return None
    try:
        response = requests.get(url, timeout=(3, 5))
    except requests.RequestException:
        return None
    if response.status_code == 200:
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        weather_info = {}

        picture = soup.find('div', class_='Wpic')
        img_tag = picture.find('img') if picture else None
        if img_tag:
            img_url = img_tag.get('src', '')
            full_img_url = requests.compat.urljoin(url, img_url)
            weather_info['img'] = full_img_url
        else:
            print('未找到圖片標籤')

        detail_section = soup.find('div', class_='detail')
        if detail_section:
            for p in detail_section.find_all('p'):
                text = p.text.strip()
                if "體感溫度" in text:
                    weather_info['feels_like'] = text.replace('：', ':').partition(':')[2].strip()
                elif "降雨機率" in text:
                    weather_info['rain_probability'] = text.replace('：', ':').partition(':')[2].strip()
                elif "紫外線" in text:
                    weather_info['uv_index'] = text.replace('：', ':').partition(':')[2].strip()
                elif "空氣品質" in text:
                    weather_info['air_quality'] = text.replace('：', ':').partition(':')[2].strip()
        return weather_info
    else:
        print(f"Failed to retrieve the page. Status code: {response.status_code}")
        return None

def get_game_questions():
    db = get_database("遊戲")
    collection = db["臺中知識王"]
    questions = list(collection.aggregate([{'$sample': {'size': 5}}]))
    return questions


def create_game_question_message(question_data, index):
    question_text = question_data['Question']
    options = [question_data['A'], question_data['B'], question_data['C'], question_data['D']]
    random.shuffle(options)

    buttons = [
        PostbackAction(label=options[i], data=urlencode({'game_answer': index, 'choice': options[i]}))
        for i in range(4)
    ]

    return TemplateSendMessage(
        alt_text='臺中知識王問題',
        template=ButtonsTemplate(
            title=f'問題 {index + 1}',
            text=question_text,
            actions=buttons
        )
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text
    if not user_id:
        return
    now = user_mode.get(user_id, "")
    if user_input == "驚喜":
        user_mode[user_id] = "驚喜"
        reply_message = TextSendMessage(
            text='請選擇您的所在區域',
            quick_reply=create_quick_reply_buttons()
        )
        line_bot_api.reply_message(event.reply_token, reply_message)
    elif user_input == "推薦":
        user_mode[user_id] = "推薦"
        reply_message = TextSendMessage(
            text='請選擇您的所在區域',
            quick_reply=create_quick_reply_buttons()
        )
        line_bot_api.reply_message(event.reply_token, reply_message)
    elif user_input == "新增":
        if not os.environ.get("ADMIN_USER_ID"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前未開放新增項目。"))
            return
        user_mode[user_id] = "新增"
        reply_message = TextSendMessage(text='請輸入項目標題')
        line_bot_api.reply_message(event.reply_token, reply_message)
    elif now == "新增" and user_input:
        if len(user_input) > 80:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="標題請限制在 80 字內。"))
            return
        # 保存用戶輸入的標題
        new_data[user_id] = {"Title": user_input}
        reply_message = TextSendMessage(
            text='請為項目評分',
            quick_reply=QuickReply(items=[
                QuickReplyButton(action=PostbackAction(label=str(i), data=f'new_rating={i}')) for i in range(1, 6)
            ])
        )
        line_bot_api.reply_message(event.reply_token, reply_message)
        user_mode.pop(user_id, None)
    elif user_input == "知識王":
        questions = get_game_questions()
        game_data[user_id] = questions
        user_scores[user_id] = 0
        question_index[user_id] = 0
        user_answers[user_id] = []
        
        if not questions:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前沒有題目。"))
            return
        first_question = create_game_question_message(questions[0], 0)
        line_bot_api.reply_message(event.reply_token, first_question)
    elif user_input in ["美食", "點心", "景點"]:
        region = user_region.get(user_id)
        user_category[user_id] = user_input
        if region and now in {"推薦", "驚喜"}:
            items = (get_random_items_from_db(user_input, region) if now == "驚喜"
                     else get_top_rated_items_from_db(user_input, region))
            messages = [create_flex_message(items, user_id)]
            if user_input == "景點":
                weather = get_weather_info(region)
                weather_text = (f"{region}：體感溫度 {weather.get('feels_like', 'N/A')}，"
                                f"降雨機率 {weather.get('rain_probability', 'N/A')}"
                                if weather else "目前無法取得天氣資訊。")
                messages.insert(0, TextSendMessage(text=weather_text))
            line_bot_api.reply_message(event.reply_token, messages)
        else:
            reply_message = TextSendMessage(text="請先選擇您的所在區域")
            line_bot_api.reply_message(event.reply_token, reply_message)
    else:
        reply_message = TextSendMessage(text="請輸入 '驚喜' 或 '推薦' 來選擇您的所在區域")
        line_bot_api.reply_message(event.reply_token, reply_message)
        
def send_to_specific_user(data):
    specific_user_id = os.environ.get('ADMIN_USER_ID')  # 替換為特定用戶的ID
    title = data.get("Title", "無標題")
    star = data.get("Star", "無評分")
    
    message = TextSendMessage(text=f"新增項目：\n標題：{title}\n評分：{star}")
    if specific_user_id:
        line_bot_api.push_message(specific_user_id, message)

def send_to_specific_user2(category, region, title, rating):
    specific_user_id = os.environ.get('ADMIN_USER_ID')  # 替換為特定用戶的ID

    
    message = TextSendMessage(text=f"新增評分：\n類別:{category}\n區域:{region}\n標題：{title}\n評分：{rating}")
    if specific_user_id:
        line_bot_api.push_message(specific_user_id, message)

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    if not user_id:
        return
    try:
        params = parse_qs(data, strict_parsing=True, max_num_fields=5)
        if any(len(v) != 1 for v in params.values()):
            raise ValueError("Duplicate parameter")
        params = {k: v[0] for k, v in params.items()}
        if 'rating' in params or 'new_rating' in params:
            rating_value = params.get('rating', params.get('new_rating'))
            if rating_value not in {'1', '2', '3', '4', '5'}:
                raise ValueError("Invalid rating")
    except ValueError:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="操作無效，請重新開始。"))
        return

    if data.startswith('region='):
        region = params.get('region')
        if region not in taichung_regions:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請選擇有效區域。'))
            return
        user_region[user_id] = region
        
        reply_message = TemplateSendMessage(
            alt_text='請選擇類別',
            template=ButtonsTemplate(
                title='請選擇服務項目',
                text='請選擇您要找的是美食、點心還是景點',
                actions=[
                    MessageAction(label='美食', text='美食'),
                    MessageAction(label='點心', text='點心'),
                    MessageAction(label='景點', text='景點')
                ]
            )
        )
        line_bot_api.reply_message(event.reply_token, reply_message)

    elif data.startswith('rating='):
        rating = params['rating']
        title = params.get('title', '')
        # 處理評分邏輯，例如更新數據庫中的評分
        if not handle_rating(user_id, title, rating, params.get('category'), params.get('region')):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="評分未儲存，請重新取得推薦。"))
            return
        reply_message = TextSendMessage(text=f"感謝您的評分！您給了 {title} {rating} 分。")
        line_bot_api.reply_message(event.reply_token, reply_message)
    elif data.startswith('new_rating='):
        rating = params['new_rating']
        if user_id in new_data:
            new_data[user_id]["Star"] = rating
            if not os.environ.get("ADMIN_USER_ID"):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前未開放新增項目。"))
                return
            send_to_specific_user(new_data[user_id])
            reply_message = TextSendMessage(text=f"已收到您的新增項目：{new_data[user_id]['Title']}，評分：{rating}，感謝你的推薦!等待後臺更新資料")
            line_bot_api.reply_message(event.reply_token, reply_message)
            new_data.pop(user_id, None)
        else:
            reply_message = TextSendMessage(text="出現錯誤，請重新嘗試新增。")
            line_bot_api.reply_message(event.reply_token, reply_message)
    elif data.startswith('game_answer='):
        try:
            index = int(params.get('game_answer', '-1'))
            choice = params['choice']
            questions = game_data.get(user_id, [])
            if not 0 <= index < len(questions) or index != question_index.get(user_id):
                raise ValueError("Stale question")
            if choice not in [questions[index][key] for key in ('A', 'B', 'C', 'D')]:
                raise ValueError("Invalid choice")
        except (ValueError, KeyError):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="此題已作答或遊戲已過期，請輸入知識王重新開始。"))
            return
        question_index[user_id] = index + 1
        correct_answer = game_data[user_id][index]['Answer']

        if choice == correct_answer:
            user_scores[user_id] += 1

        user_answers[user_id].append(choice)
        
        # 發送選擇的答案
        choice_message = TextSendMessage(text=f"你選擇了: {choice}\n答案是:{correct_answer}")
        messages = [choice_message]
        
        if index + 1 < len(game_data[user_id]):
            next_question = create_game_question_message(game_data[user_id][index + 1], index + 1)
            messages.append(next_question)
        else:
            final_score = round(user_scores[user_id] * 100 / len(game_data[user_id]))
            total_questions = len(game_data[user_id])
            if final_score == 0:
                score_message = f"遊戲結束！你的最終得分是 {final_score}\n太誇張了吧。"
            elif final_score == 20 or final_score == 40:
                score_message = f"遊戲結束！你的最終得分是 {final_score}\n可以多來台中旅遊。"
            elif final_score == 60 or final_score == 80:
                score_message = f"遊戲結束！你的最終得分是 {final_score}\n離成為台中地頭蛇更進一步。"
            elif final_score == 100:
                score_message = f"遊戲結束！你的最終得分是 {final_score}\n好厲害!不愧是臺中地頭蛇。"
            else:
                score_message = f"遊戲結束！你的最終得分是 {final_score}"
            messages.append(TextSendMessage(text=score_message))
            for mapping in (game_data, user_scores, question_index, user_answers):
                mapping.pop(user_id, None)
        line_bot_api.reply_message(event.reply_token, messages)
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="操作無效，請重新開始。"))


def handle_rating(user_id, title, rating, category=None, region=None):
    if category not in {"美食", "點心", "景點"} or region not in taichung_regions:
        return False
    if str(rating) not in {"1", "2", "3", "4", "5"} or not title:
        return False
    collection = get_database(category)[region]
    # One atomic update prevents concurrent ratings from overwriting each other.
    result = collection.update_one({"Title": title}, [
        {"$set": {
            "Count": {"$add": [{"$convert": {"input": "$Count", "to": "int", "onError": 1, "onNull": 1}}, 1]},
            "_rating_sum": {"$add": [
                {"$ifNull": ["$_rating_sum", {"$multiply": [
                    {"$convert": {"input": "$Star", "to": "double", "onError": 0, "onNull": 0}},
                    {"$convert": {"input": "$Count", "to": "int", "onError": 1, "onNull": 1}}
                ]}]}, float(rating)]}
        }},
        {"$set": {"Star": {"$round": [{"$divide": ["$_rating_sum", "$Count"]}, 1]}}}
    ])
    return result.matched_count == 1


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
