# Product Glossary

This glossary defines the canonical terminology used across product, architecture, specifications, code, and agent instructions.

Agents should prefer these terms consistently and avoid introducing synonyms for established concepts.

---

## Book

A literary work available for reading in the platform.

Initial book:

> *The Fall of the House of Usher* — Edgar Allan Poe

---

## Book Version

A specific immutable representation of a book's canonical text.

Annotations always belong to a specific book version through their paragraph.

---

## Chapter

A structural section of a book version.

---

## Paragraph

The smallest canonical text unit used by the annotation system.

Annotations reference paragraphs rather than pages.

---

## Text Range

A position inside a paragraph defined by:

```text
start_offset
end_offset
```

Ranges use half-open UTF-16 offsets:

```text
[start_offset, end_offset)
```

---

## Highlight

An annotation representing a marked text range without user-authored note content.

---

## Note

An annotation attached to a text range that contains user-authored content.

---

## Annotation

A generic term for a user's mark on a passage.

An annotation may be:

```text
highlight
note
```

Annotations are the parent context for comments.

---

## Comment

A user-authored response attached to an annotation.

A comment may optionally have a parent comment.

---

## Reply

A comment whose `parent_comment_id` points to another comment in the same annotation thread.

---

## Thread

An annotation together with its comments and replies.

```text
Annotation
 └── Thread
      ├── Comment
      │    ├── Reply
      │    └── Reply
      └── Comment
```

---

## Reader

Any person using the platform to read the book.

A reader may be anonymous or authenticated.

---

## Authenticated Reader

A reader with an active application account.

Authenticated readers can create and manage their own annotations and comments.

---

## Application User

The internal representation of an authenticated reader in Usher Library.

The application user is identified by an internal UUID.

---

## Keycloak Identity

The external identity managed by Keycloak.

It is mapped to an application user through the OIDC `sub` value.

---

## Reader Identity

The visual and public representation of an application user inside the reading experience.

It includes:

- username
- display name
- handwriting style
- ink style
- paper texture

---

## Handwriting Style

The visual typeface used to render a reader's annotations.

It represents the reader's visual identity but is not stored directly inside annotations.

---

## Ink Style

The visual appearance of a reader's annotation ink.

---

## Paper Texture

A visual texture applied to the reading experience.

---

## Margin

The visual space surrounding the text in desktop book mode.

Annotations may be rendered inside the margin.

The margin does not exist as a persistent domain object.

---

## Annotation Density

A derived measure representing how strongly a passage has been marked by readers.

It may affect:

- margin activity
- mobile markers
- page wear

Density is derived data, not canonical domain state.

---

## Page Wear

A visual effect representing accumulated reader interaction with a page.

It is derived from annotation activity and is not stored as canonical database state.

---

## Book Mode

Desktop-oriented reading mode presenting the work as a physical-style book, typically using two pages.

---

## Scroll Mode

Continuous vertical reading mode.

It is the primary mobile presentation and an alternative desktop presentation.

---

## Reading Position

The reader's current location in the book's canonical content.

A reading position should reference canonical content rather than visual page coordinates.

---

## Annotation Toolbar

The contextual UI displayed after selecting text.

Initial actions:

```text
Highlight
Annotate
```

---

## Bottom Sheet

A mobile UI panel that slides upward from the bottom of the screen.

Used for contextual annotation threads and responses.

---

## Public Content

Content intentionally visible without authentication.

Initial public content includes:

- book text
- highlights
- public annotations
- comments
- replies
- public reader identity information

---

## User-Generated Content

Content created by readers.

Includes:

- annotations
- notes
- comments
- replies

It must always be treated as untrusted input.

---

## Moderation

Administrative management of user-generated content and user accounts.

Examples:

- hiding comments
- deleting inappropriate content
- suspending users

---

## Reader

The default application role for authenticated users.

```text
READER
```

---

## Administrator

An authenticated user with elevated application privileges.

```text
ADMIN
```

Administrators can perform moderation and other explicitly authorized actions.

---

## Session

The server-side authenticated state connecting a browser to an application user.

The browser holds only an opaque session identifier.

---

## Source Text

The approved canonical literary text from the project's source.

For the initial book, the source is Project Gutenberg.

---

## Canonical Text

The exact text stored in the published `BookVersion`.

It is the authoritative reference for annotation ranges.

---

## Marginalia

The collective visual concept of reader annotations surrounding the book text.

This is a product concept rather than a database entity.

---

## Shared Reading

The experience of reading the same literary work alongside the marks and interpretations of other readers.

This is the central product concept.

---

## Terminology Rules

Use these terms consistently:

| Prefer | Avoid |
|---|---|
| Annotation | Mark, marker, annotation note |
| Highlight | Underline object |
| Note | Annotation message |
| Comment | Message |
| Reply | Child comment |
| Thread | Discussion tree |
| Paragraph | Text block |
| Text Range | Text coordinates |
| Book Version | Edition object |
| Reader | User, when referring to a person reading |
| Application User | Account, when referring to the database identity |
| Session | Login token |
| Margin | Sidebar |
| Book Mode | Pagination mode |
| Scroll Mode | Feed mode |

When a concept does not match an existing glossary term exactly, prefer the established domain terminology over inventing a new synonym.