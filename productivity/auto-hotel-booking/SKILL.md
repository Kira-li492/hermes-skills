---
name: auto-hotel-booking
description: 自动订酒店流程——通过本地Chrome浏览器操作Hilton、Marriott等酒店官网，从搜索到付款页面的完整pipeline。适用于Kira先生授权后的真实订房操作。
version: 1.0.0
author: kira
---

# 自动订酒店 Skill

## 前提条件

1. 本地Chrome已启动（cdp_url: http://localhost:9222）
2. 用户已在Chrome里登录目标酒店账号（Hilton Honors / Marriott Bonvoy等）
3. 付款信息已保存在账号里，或用户当面提供

## 已知信息

- Kira先生 Hilton Honors 账号：kira1597310@gmail.com
- Kira先生 Marriott Bonvoy 账号：kira1597310@gmail.com（注册名 Xiangshi Lee，2024年11月）
- Marriott Bonvoy 有反爬虫，未登录状态返回800错误，必须先登录

---

## Hilton 订房 Pipeline（已验证可用）

### Step 1：直接构建房型页URL

```
https://www.hilton.com/en/book/reservation/rooms/?ctyhocn=HOTEL_CODE&arrivalDate=YYYY-MM-DD&departureDate=YYYY-MM-DD&room1NumAdults=1
```

常用酒店代码：
- Hilton Santa Barbara Beachfront Resort：SBAFPHH

### Step 2：用 textContent 找房间按钮（不要用href）

Hilton是SPA React应用，按钮没有href，必须用JS搜索：

```javascript
Array.from(document.querySelectorAll('button'))
  .filter(b => /Book From \$/.test(b.textContent.trim()))
  .map(b => b.textContent.trim())
```

点击目标房型：
```javascript
Array.from(document.querySelectorAll('button'))
  .find(b => b.textContent.includes('Book From $XXX'))
  .click()
```

### Step 3：Rate选择页（/book/reservation/rates/）

```javascript
Array.from(document.querySelectorAll('button'))
  .filter(b => /Select.*\$\d+/.test(b.textContent))
  .map(b => b.textContent.trim())
// 选Honors Discount最便宜，或按用户要求选
```

### Step 4：Customize页（/book/reservation/customize/）

```javascript
Array.from(document.querySelectorAll('button'))
  .find(b => b.textContent.trim() === 'Continue to Payment')
  .click()
```

### Step 5：付款页（/book/reservation/payment/）

**到此停下，向用户确认所有信息后再继续。**

真实订房需要：
- 确认房型、日期、价格
- 信用卡信息（用户提供或账号已保存）
- 用户明确说"确认订"才提交

---

## Marriott / Ritz-Carlton Pipeline

**注意：Marriott反爬虫严重，必须登录状态才能操作。**

登录后直接用搜索框：
1. 导航到 https://www.marriott.com
2. 在搜索框输入酒店名，选日期
3. 同样用 textContent 搜索按钮操作

Ritz-Carlton属于Marriott体系，订房最终跳转到marriott.com。

---

## 通用SPA订房原则

1. **不信任href，只信任textContent** — SPA网站按钮都是JS事件，没有href
2. **不用CSS类名选元素** — 类名是哈希或语义不固定，大小写敏感容易失效
3. **用 `Array.from(document.querySelectorAll('button')).filter(b=>...)` 定位按钮**
4. **每步等待3-4秒** — SPA页面切换需要等JS渲染完成
5. **用 window.location.href 确认当前步骤** — 确保页面跳转成功

---

## 安全规则

- 付款页前必须向用户展示完整订单信息（酒店、日期、房型、价格）
- 用户明确说"确认"或"提交"才点最终付款按钮
- 绝不在未确认状态下提交付款

---

## Pitfalls

- Marriott未登录 → 800错误页，换登录状态或用Booking.com
- Hilton房型用CSS类名选 → querySelectorAll返回0，改用textContent搜索
- 页面加载不等待 → 按钮还没渲染，sleep 3-4秒再操作
- Ritz-Carlton独立URL → 已失效，全部走marriott.com
