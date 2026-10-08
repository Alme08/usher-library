# Product Vision

## 1. Product

Usher Library is a digital reading space where a literary work becomes a shared object of interpretation.

The initial experience is centered on *The Fall of the House of Usher* by Edgar Allan Poe.

The product combines:

```text
Literary reading
+
Personal annotation
+
Collective marginalia
```

The goal is to make the reader feel that they are reading a real book that has been gradually marked, discussed, and worn by other readers.

---

## 2. Product Vision

> **Turn reading into a visible conversation between readers across time.**

The book remains the protagonist.

Social interaction exists around the text, not instead of it.

---

## 3. Target Experience

A user should feel:

- immersed in the book
- curious about what other readers noticed
- encouraged to leave their own interpretation
- visually connected to the history of previous readings

The interface should feel closer to:

```text
annotated book
+
personal notebook
+
quiet reading room
```

than to:

```text
social network
+
comment feed
+
generic ebook reader
```

---

## 4. Core User Journey

### Anonymous reader

```text
Open library
   ↓
Open book
   ↓
Read
   ↓
Notice annotations from others
   ↓
Explore contextual discussions
   ↓
Decide to participate
```

### Authenticated reader

```text
Login
   ↓
Read
   ↓
Select passage
   ↓
Highlight / annotate
   ↓
See personal writing style
   ↓
Read responses
   ↓
Join the conversation
```

---

## 5. Core Product Concepts

### The Book

The book is the primary interface and source of context.

### The Margin

Annotations visually occupy the space around the text, recreating the feeling of physical marginalia.

### The Collective Mark

The density of highlights communicates which passages attracted attention from other readers.

### The Reader's Hand

Each reader has a visual identity through handwriting, ink, and texture.

### The Worn Page

Repeated interaction subtly changes the visual appearance of the page, representing accumulated reading history.

---

## 6. Product Principles

### 6.1 The book comes first

Interaction must never overwhelm the reading experience.

### 6.2 Context over feeds

Comments belong to passages.

There is no primary global social feed in the initial product.

### 6.3 Quiet social interaction

The product should encourage curiosity and interpretation rather than engagement farming.

Avoid mechanics such as:

- likes
- follower counts
- popularity rankings
- infinite feeds
- notification overload

### 6.4 Personal but shared

Each reader leaves a distinct visual mark while participating in the same shared book.

### 6.5 Simple interaction

Selecting text should make the next action obvious:

```text
Subrayar
Anotar
```

### 6.6 Progressive complexity

The first interaction should be understandable without learning the system.

Advanced capabilities should emerge naturally as the reader explores.

---

## 7. Visual Direction

The interface should evoke:

```text
old book
+
quiet library
+
handwritten marginalia
+
subtle wear
```

Desired qualities:

- literary
- tactile
- warm
- atmospheric
- restrained
- slightly melancholic

Avoid:

- generic SaaS aesthetics
- excessive gradients
- gamification-heavy UI
- noisy social-media layouts
- decorative effects that reduce readability

---

## 8. Desktop Experience

Desktop should take advantage of available horizontal space.

The reader should have:

- readable page dimensions
- genuine margins
- contextual notes
- annotation-density indicators
- comfortable typography

The margin is part of the reading experience rather than a separate sidebar.

---

## 9. Mobile Experience

Mobile should preserve the concept without attempting to reproduce the desktop layout literally.

Use:

- continuous reading
- small annotation indicators
- contextual bottom sheets
- minimal selection actions

There is no persistent annotation margin on mobile.

---

## 10. Success Criteria

The product succeeds when a reader can:

1. Open the book without creating an account.
2. Read comfortably on desktop and mobile.
3. Understand that annotations belong to specific passages.
4. Discover what other readers marked or discussed.
5. Add their own mark with minimal friction.
6. Recognize their own visual identity in the book.
7. Move between reading and discussion without losing context.

---

## 11. Non-Goals

The product is not intended to become:

- a general social network
- a Goodreads replacement
- a generic ebook platform
- a publishing platform
- a chat application
- a productivity tool
- a recommendation engine

The initial product should remain focused on the experience of **reading one book together**.

---

## 12. Initial Product Scope

The first release contains:

```text
1 book
1 reading experience
1 user identity system
annotations
highlights
contextual comments
reader profiles
moderation
```

Additional books and collaborative features come later.

---

## 13. Future Direction

The architecture may eventually support:

- multiple literary works
- more annotation types
- live collaborative reading
- reading history
- richer moderation
- curated editions
- thematic reading rooms

These features must preserve the core principle:

> **The text remains the center of the experience.**