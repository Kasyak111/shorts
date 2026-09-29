"""
Russian Grammar & Punctuation Corrector for Whisper Subtitles.
Fixes agreement errors (e.g., 'одно обойма' -> 'одна обойма', 'первый встреча' -> 'первая встреча')
and cleans Whisper garbage punctuation (e.g., '?..', '!..', '??.', '....').
"""

import os
import re
import sys
from typing import List, Optional, Set, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import pymorphy3
except ImportError:
    import pymorphy2 as pymorphy3


# Offline rules: Blogger promos, CTAs, watermarks to strip
PROMO_PATTERNS = [
    # "с вами был...", "с вами была..."
    r"\bс\s+вами\s+был[а-яё]*(\s+[A-Za-zА-Яа-яЁё]+(\s+[A-Za-zА-Яа-яЁё]+)?)?\b",
    # "подпишись...", "подписывайтесь...", "не забудь подписаться..."
    r"\b(не\s+забудь(те)?\s+)?(подпишись|подпишитесь|подписывайся|подписывайтесь|подписаться)(\s+на\s+(наш\s+)?(тг[-\s]*канал|канал|телеграм|telegram|профиль))?\b",
    r"\b(подпиши|подпишите)\s+на\s+(наш\s+)?(тг[-\s]*канал|канал|телеграм|telegram|профиль)\b",
    r"\bподписка\s+на\s+(наш\s+)?(тг[-\s]*канал|канал|телеграм|telegram|профиль)\b",
    r"^\s*подписка\s*$",
    # "ставьте лайк...", "лайк и подписка...", "жми лайк..."
    r"\b(ставь|ставьте|жми|жмите|поставь|поставьте)\s+лайк[а-яё]*(\s+и\s+колокольчик[а-яё]*)?\b",
    r"\bлайк\s+и\s+подписк[а-яё]*\b",
    r"\bлайки?\s+(и\s+)?колокольчик[а-яё]*\b",
    # "колокольчик" only in CTA context
    r"\b(жми|жмите|нажми|нажмите|ставь|ставьте)\s+(на\s+)?колокольчик[а-яё]*\b",
    # "ютуб канал", "наш ютуб", "телеграм канал", "тг канал"
    r"\b(наш\s+)?(ютуб|youtube|тг|телеграм|telegram)[-\s]+канал[а-яё]*\b",
    # "русский дубляж"
    r"\bрусский\s+дубляж\b",
    # "художественный фильм", "художественного фильма"
    r"\bхудожественн[а-яё]+\s+фильм[а-яё]*\b",
    # "перевод и субтитры", "редактор субтитров", "автор субтитров" (strictly credit context)
    r"\b(перевод|редактор|автор)\s+(и\s+)?субтитр[а-яё]*\b",
    # "озвучено", "озвучка" in studio/dub context
    r"\b(озвучено|озвучка)\s+(студией|по\s+версии|каналом|командой|специально\s+для)(\s+[A-Za-zА-Яа-яЁё0-9_-]+)*\b",
    # "ссылка в описании", "код в закрепе", "код фильма в описании"
    r"\bссылк[а-яё]\s+в\s+(описании|шапке(\s+профиля)?|профиле|закрепе|комментариях)\b",
    r"\bкод\s+(фильма\s+)?в\s+(закрепе|комментариях|описании|шапке(\s+профиля)?|профиле)\b",
    # "спасибо за просмотр", "до скорой встречи", "продолжение следует"
    r"\bспасибо\s+за\s+просмотр\b",
    r"\bдо\s+скорой\s+встречи\b",
    r"\bпродолжение\s+следует\b",
    # "спонсор показа", "при поддержке"
    r"\b(спонсор\s+показа|при\s+поддержке)\b",
    r"\bdima\s+torzhok\b",
]

# Vocative mishearings / oblique cases -> Nominative vocative form
VOCATIVE_MAP = {
    "босса": "босс",
    "командира": "командир",
    "шефа": "шеф",
    "майора": "майор",
    "капитана": "капитан",
    "сержанта": "сержант",
    "лейтенанта": "лейтенант",
    "полковника": "полковник",
    "генерала": "генерал",
    "адмирала": "адмирал",
    "доктора": "доктор",
    "профессора": "профессор",
    "сэра": "сэр",
    "офицера": "офицер",
    "агента": "агент",
    "братана": "братан",
    "братишки": "братишка",
}

# Standard vocatives in nominative case (for comma insertion and preservation)
NOMINATIVE_VOCATIVES = {
    "босс", "командир", "шеф", "майор", "капитан", "сержант",
    "лейтенант", "полковник", "генерал", "адмирал", "доктор",
    "профессор", "сэр", "офицер", "агент", "братан", "братишка",
    "дружище", "парень", "парни", "ребята",
}


class RussianGrammarCorrector:
    """
    Cleans punctuation and corrects grammatical agreement in Russian sentences,
    specifically designed for AI speech recognition (Whisper) post-processing.
    """

    def __init__(self, morph: Optional[pymorphy3.MorphAnalyzer] = None):
        self.morph = morph if morph is not None else pymorphy3.MorphAnalyzer()

    def sanitize_punctuation(self, text: str) -> str:
        """
        Cleans abnormal punctuation artifacts common in Whisper AI outputs:
        - Replaces '?..' with '?'
        - Replaces '!..' with '!'
        - Replaces '??' with '?', '!!' with '!', '....' with '...'
        - Removes dangling dots after '?' and '!'
        - Removes redundant spaces before punctuation marks
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        # 1. Remove spaces before punctuation marks
        text = re.sub(r"[ \t]+([,.:;?!…])", r"\1", text)

        # 2. 4 or more dots -> 3 dots (...)
        text = re.sub(r"\.{4,}", "...", text)

        # 3. Repeated question marks / exclamation marks with dots
        # '?..', '??.', '???', '?.' -> '?'
        text = re.sub(r"\?[\?.]+", "?", text)
        # '!..', '!!.', '!!!', '!.' -> '!'
        text = re.sub(r"![\!.]+", "!", text)

        # 4. Remove any remaining dot directly after ? or ! (e.g., '?!.')
        text = re.sub(r"([?!])\.", r"\1", text)

        # 5. Clean duplicate whitespace
        text = re.sub(r"[ \t]{2,}", " ", text)

        return text.strip()

    def _apply_case(self, original_word: str, new_word: str) -> str:
        """Preserves original word capitalization (UPPERCASE, Titlecase, lowercase)."""
        if not original_word or not new_word:
            return new_word
        if original_word.isupper():
            return new_word.upper()
        elif original_word[0].isupper() and (len(original_word) == 1 or original_word[1:].islower()):
            return new_word.capitalize()
        elif original_word.islower():
            return new_word.lower()
        elif original_word.istitle():
            return new_word.title()
        return new_word

    def _is_modifier(self, word: str) -> bool:
        """Checks if a word is an adjectival modifier or gender-declining numeral."""
        parses = self.morph.parse(word)
        if not parses:
            return False

        p0 = parses[0]
        # Full adjectives and full participles
        if p0.tag.POS in ("ADJF", "PRTF"):
            return True

        # Numerals with gender declension (e.g., два/две, оба/обе, полтора/полторы)
        if p0.tag.POS == "NUMR":
            if any(p.tag.gender is not None for p in parses):
                return True

        # Check if secondary parse is ADJF with reasonable score or Apro/Subx pronoun
        for p in parses:
            if p.tag.POS in ("ADJF", "PRTF"):
                score = p.score or 0
                if "Apro" in p.tag.grammemes or "Subx" in p.tag.grammemes or score >= 0.20:
                    if parses[0].tag.POS in ("PRCL", "CONJ", "PREP"):
                        continue
                    return True

        return False

    def _is_noun(self, word: str) -> bool:
        """Checks if a word is a noun (excluding surname-only parses)."""
        parses = self.morph.parse(word)
        if not parses:
            return False

        nouns = [p for p in parses if p.tag.POS == "NOUN"]
        if not nouns:
            return False

        # Filter out rare surname/patronymic parses if a regular noun exists
        std_nouns = [p for p in nouns if not {"Surn", "Patr"}.intersection(p.tag.grammemes)]
        if std_nouns:
            nouns = std_nouns

        return (nouns[0].score or 0) >= 0.15 or parses[0].tag.POS == "NOUN"

    def _is_adverb(self, word: str) -> bool:
        """Checks if a word is an adverb (can appear inside modifier chains, e.g. 'очень')."""
        parses = self.morph.parse(word)
        return bool(parses and parses[0].tag.POS == "ADVB")

    def _correct_modifier(self, dep_word: str, noun_word: str) -> str:
        """Inflects modifier word to agree in gender, number, and case with the head noun."""
        dep_parses = self.morph.parse(dep_word)
        noun_parses = self.morph.parse(noun_word)

        mod_parses = [p for p in dep_parses if p.tag.POS in ("ADJF", "PRTF", "NUMR")]
        n_parses = [p for p in noun_parses if p.tag.POS == "NOUN"]

        if not mod_parses or not n_parses:
            return dep_word

        # Prefer non-surname nouns
        std_nouns = [p for p in n_parses if not {"Surn", "Patr"}.intersection(p.tag.grammemes)]
        if std_nouns:
            n_parses = std_nouns

        p_dep_top = mod_parses[0]
        p_noun_top = n_parses[0]

        # Handle numerals with gender (два / две, оба / обе)
        if p_dep_top.tag.POS == "NUMR":
            if any(p.tag.gender is not None for p in mod_parses):
                noun_gender = p_noun_top.tag.gender
                if noun_gender:
                    for p in mod_parses:
                        if p.tag.gender == noun_gender:
                            return dep_word
                    inf = p_dep_top.inflect({noun_gender, p_dep_top.tag.case or "nomn"})
                    if inf:
                        return inf.word
            return dep_word

        # Check if already in agreement (ADJF / PRTF)
        for p_dep in mod_parses:
            for p_noun in n_parses:
                if p_dep.tag.number == p_noun.tag.number and p_dep.tag.case == p_noun.tag.case:
                    if p_noun.tag.number == "plur" or p_dep.tag.gender == p_noun.tag.gender:
                        return dep_word

        # Select best pair to inflect
        best_pair = None
        best_score = -1.0

        for p_dep in mod_parses:
            for p_noun in n_parses:
                score = 0.0
                if p_dep.tag.number == p_noun.tag.number:
                    score += 10.0
                if p_dep.tag.case == p_noun.tag.case:
                    score += 5.0
                score += (p_noun.score or 0.0) * 2.0 + (p_dep.score or 0.0)
                if score > best_score:
                    best_score = score
                    best_pair = (p_dep, p_noun)

        if not best_pair:
            return dep_word

        p_dep, p_noun = best_pair
        target_grammemes = set()
        if p_noun.tag.number:
            target_grammemes.add(p_noun.tag.number)
        if p_noun.tag.case:
            target_grammemes.add(p_noun.tag.case)
        if p_noun.tag.number != "plur" and p_noun.tag.gender:
            target_grammemes.add(p_noun.tag.gender)
        if p_noun.tag.case == "accs" and (p_noun.tag.gender == "masc" or p_noun.tag.number == "plur"):
            if p_noun.tag.animacy:
                target_grammemes.add(p_noun.tag.animacy)

        inflected = p_dep.inflect(target_grammemes)
        if inflected:
            return inflected.word

        # Fallback without animacy
        target_no_anim = {g for g in target_grammemes if g not in ("anim", "inan")}
        inflected = p_dep.inflect(target_no_anim)
        if inflected:
            return inflected.word

        return dep_word

    def correct_agreements(self, text: str) -> str:
        """
        Analyzes word chains (adjective/pronoun/numeral + noun) and corrects
        gender/number/case agreement errors while preserving original casing.
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        # Split into tokens preserving all separators and punctuation
        tokens = re.split(r"([^\W\d_]+(?:-[^\W\d_]+)?)", text)
        word_indices = [
            i for i, t in enumerate(tokens)
            if t and re.match(r"^[^\W\d_]+(?:-[^\W\d_]+)?$", t)
        ]

        i = 0
        while i < len(word_indices):
            w_idx = word_indices[i]
            word = tokens[w_idx]

            # Look ahead for a modifier chain ending in a noun
            if self._is_modifier(word.lower()):
                chain_indices = [w_idx]
                j = i + 1
                found_noun = False
                noun_idx = -1
                noun_word = ""

                while j < len(word_indices):
                    # Ensure only whitespace between consecutive words in chain
                    prev_w_idx = word_indices[j - 1]
                    curr_w_idx = word_indices[j]
                    between = "".join(tokens[prev_w_idx + 1 : curr_w_idx])
                    if not re.fullmatch(r"\s*", between):
                        break

                    next_w = tokens[curr_w_idx]
                    next_lower = next_w.lower()

                    # Adverbs (e.g. очень) can appear inside modifier chain
                    if self._is_adverb(next_lower):
                        j += 1
                        continue

                    if self._is_modifier(next_lower):
                        chain_indices.append(curr_w_idx)
                        j += 1
                        continue
                    elif self._is_noun(next_lower):
                        noun_idx = curr_w_idx
                        noun_word = next_lower
                        found_noun = True
                        break
                    else:
                        break

                if found_noun and noun_word:
                    for mod_idx in chain_indices:
                        orig_mod = tokens[mod_idx]
                        corrected = self._correct_modifier(orig_mod.lower(), noun_word)
                        tokens[mod_idx] = self._apply_case(orig_mod, corrected)
                    i = j + 1
                    continue

            i += 1

        return "".join(tokens)

    def is_blogger_promo(self, text: str) -> bool:
        """Returns True if the text contains blogger promotional voiceover, CTA, or channel watermark."""
        if not text or not isinstance(text, str):
            return False
        clean = re.sub(r"\{.*?\}", "", text).strip()
        for pat in PROMO_PATTERNS:
            if re.search(pat, clean, re.IGNORECASE):
                return True
        return False

    def strip_blogger_promos(self, text: str) -> str:
        """
        Removes blogger promotional voiceovers, CTAs, and watermarks.
        If the entire phrase is promotional, returns "".
        If a promotional clause is attached, strips the promo and keeps character dialogue.
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        result = text
        for pat in PROMO_PATTERNS:
            while True:
                match = re.search(pat, result, re.IGNORECASE)
                if not match:
                    break
                start, end = match.span()
                before = result[:start].strip(" ,;:-—–")
                after = result[end:].strip(" ,;:-—–")
                if not before and not after:
                    return ""
                if before and not after:
                    result = before
                elif not before and after:
                    result = after
                elif before and after:
                    result = f"{before} {after}"

        result = re.sub(r"^[,;:\-—–\s]+|[,;:\-—–\s]+$", "", result)
        return result

    def correct_action_phonetics(self, text: str) -> str:
        """
        Corrects common acoustic speech recognition (Whisper) mishearings in action movies.
        E.g.: 'семь назад' -> 'всем назад', 'ахи лез' -> 'ахиллес', 'к жёном' -> 'к жёнам'.
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        def replace_with_case(orig_match: re.Match, replacement: str) -> str:
            matched_str = orig_match.group(0)
            if matched_str.isupper():
                return replacement.upper()
            elif matched_str[0].isupper():
                return replacement.capitalize()
            return replacement.lower()

        # 1. 'семь назад' / 'все назад' / 'се назад' / 'в 7 назад' -> 'всем назад'
        text = re.sub(
            r"\b(семь|все|се|в\s+семь|в\s+7)\s+назад\b",
            lambda m: replace_with_case(m, "всем назад"),
            text,
            flags=re.IGNORECASE,
        )

        # 2. 'ахи лез' / 'ахилес' -> 'ахиллес'
        text = re.sub(
            r"\b(ахи\s+лез|ахилес)\b",
            lambda m: replace_with_case(m, "ахиллес"),
            text,
            flags=re.IGNORECASE,
        )

        # 3. 'дедшот' / 'дэд шот' / 'дед шот' -> 'дэдшот'
        text = re.sub(
            r"\b(дедшот|дэд\s+шот|дед\s+шот)\b",
            lambda m: replace_with_case(m, "дэдшот"),
            text,
            flags=re.IGNORECASE,
        )

        # 4. 'григс' / 'григз' -> 'григгс'
        text = re.sub(
            r"\b(григс|григз)\b",
            lambda m: replace_with_case(m, "григгс"),
            text,
            flags=re.IGNORECASE,
        )

        # 5. 'к жёном' / 'к женом' -> 'к жёнам'
        text = re.sub(
            r"\bк\s+ж[её]ном\b",
            lambda m: replace_with_case(m, "к жёнам"),
            text,
            flags=re.IGNORECASE,
        )

        # 6. 'этим подонками' -> 'этими подонками'
        text = re.sub(
            r"\bэтим\s+подонками\b",
            lambda m: replace_with_case(m, "этими подонками"),
            text,
            flags=re.IGNORECASE,
        )

        # 7. 'огонь поражение' -> 'огонь на поражение'
        text = re.sub(
            r"\bогонь\s+поражение\b",
            lambda m: replace_with_case(m, "огонь на поражение"),
            text,
            flags=re.IGNORECASE,
        )

        return text

    def _is_transitive_verb(self, word: str) -> bool:
        """Checks if a word is a transitive verb (VERB or INFN with 'tran' tag)."""
        if not word:
            return False
        # Special case: 'стрелять' in colloquial cinema dialogue is intransitive directional ('куда стрелять, генерал?')
        if word.lower() == "стрелять":
            return False
        parses = self.morph.parse(word)
        return any(p.tag.POS in ("VERB", "INFN") and "tran" in p.tag for p in parses)

    def _is_indicative_verb(self, word: str) -> bool:
        """Checks if a word is a 3rd person or past indicative verb (subject-predicate sentence)."""
        if not word:
            return False
        parses = self.morph.parse(word)
        # If it has an imperative parse (e.g. 'разрешите', 'скажите', 'помогите'), it's an imperative trigger
        if any(p.tag.POS == "VERB" and "impr" in p.tag for p in parses):
            return False
        for p in parses:
            if p.tag.POS == "VERB" and "indc" in p.tag:
                if "3per" in p.tag or "past" in p.tag:
                    return True
        return False

    def _is_vocative_trigger_after(self, word: str, tail: str) -> bool:
        """
        Checks if the word/tail following a potential sentence-start vocative
        indicates a true vocative address.
        Triggers: 1st/2nd person pronoun, imperative verb, question word, interjection,
        or alert/attention phrases ('тревога', 'назад', 'всё в порядке', 'так точно', 'приказ выполнен').
        """
        if not word:
            return False
        w = word.lower()
        t_low = tail.lower().strip()
        # 1st/2nd person pronouns
        if w in {"я", "мы", "ты", "вы", "мне", "нам", "тебе", "вам", "меня", "нас", "тебя", "вас"}:
            return True
        # Question words
        if w in {"где", "куда", "как", "что", "кто", "когда", "зачем", "почему", "откуда", "какой", "какая", "какие"}:
            return True
        # Interjections / particles
        if w in {"эй", "ну", "а", "давай", "давайте", "здорово", "привет", "салют", "пожалуйста"}:
            return True
        # Attention / military status cues
        if w in {"назад", "тревога", "внимание", "отбой", "огонь", "стоп", "стой", "готов", "готовы", "приказ"}:
            return True
        if t_low.startswith("всё в порядке") or t_low.startswith("все в порядке") or t_low.startswith("так точно"):
            return True
        # Imperative verbs
        parses = self.morph.parse(w)
        if any(p.tag.POS == "VERB" and "impr" in p.tag for p in parses):
            return True
        return False

    def correct_vocatives(self, text: str) -> str:
        """
        Normalizes character vocative addresses to nominative case with proper punctuation:
        - 'босса' -> 'босс', 'командира' -> 'командир', 'шефа' -> 'шеф'
        - Ensures comma separation: 'БОСС, МЫ ГОТОВЫ', 'МЫ ГОТОВЫ, БОСС'
        - Does NOT alter legitimate genitive/accusative objects (e.g., 'видел босса', 'у шефа')
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        NON_VOCATIVE_PREPS = {
            "у", "для", "без", "от", "до", "из", "из-за", "против", "около",
            "возле", "насчет", "на счёт", "вместо", "ради", "после", "кроме", "к", "ко"
        }

        # 1. Standalone cue: e.g. "БОССА!" -> "БОСС!"
        m_solo = re.fullmatch(r"^([^\W\d_]+)([\s!?.]*)$", text.strip())
        if m_solo:
            w_raw, punct = m_solo.group(1), m_solo.group(2)
            w_low = w_raw.lower()
            if w_low in VOCATIVE_MAP:
                rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                return f"{rep}{punct}"

        # 2. Inside clauses: "..., босса, ..." -> "..., босс, ..."
        def repl_mid(match: re.Match) -> str:
            pre_punct = match.group(1)
            w_raw = match.group(2)
            post_punct = match.group(3)
            w_low = w_raw.lower()
            if w_low in VOCATIVE_MAP:
                rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                return f"{pre_punct}{rep}{post_punct}"
            return match.group(0)

        text = re.sub(
            r"([,!?…]\s+)([^\W\d_]+)(\s*[,!?…])",
            repl_mid,
            text
        )

        # 3. Interjection + vocative: "эй босса" -> "эй, босс", "эй босс" -> "эй, босс"
        def repl_interjection(match: re.Match) -> str:
            interj = match.group(1)
            w_raw = match.group(2)
            w_low = w_raw.lower()
            if w_low in VOCATIVE_MAP:
                rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                return f"{interj}, {rep}"
            elif w_low in NOMINATIVE_VOCATIVES:
                return f"{interj}, {w_raw}"
            return match.group(0)

        text = re.sub(
            r"\b(эй|слушай|послушай|смотри)\s+([^\W\d_]+)\b",
            repl_interjection,
            text,
            flags=re.IGNORECASE
        )

        # 4. At sentence start: "БОССА МЫ ГОТОВЫ" -> "БОСС, МЫ ГОТОВЫ"
        m_start = re.match(r"^([^\W\d_]+)([,:\s]+)(.*)$", text)
        if m_start:
            w_raw = m_start.group(1)
            sep = m_start.group(2)
            tail = m_start.group(3)
            w_low = w_raw.lower()
            next_word_m = re.match(r"^([^\W\d_]+)", tail)
            next_word = next_word_m.group(1).lower() if next_word_m else ""

            is_followed_by_indicative = self._is_indicative_verb(next_word)
            is_voc_trigger = self._is_vocative_trigger_after(next_word, tail)

            if "," in sep:
                if w_low in VOCATIVE_MAP:
                    rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                    text = f"{rep}{sep}{tail}"
            else:
                if is_voc_trigger and not is_followed_by_indicative:
                    if w_low in VOCATIVE_MAP:
                        rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                        text = f"{rep}, {tail.strip()}"
                    elif w_low in NOMINATIVE_VOCATIVES:
                        text = f"{w_raw}, {tail.strip()}"

        # 5. At sentence end: "МЫ ГОТОВЫ БОССА" -> "МЫ ГОТОВЫ, БОСС"
        m_end = re.search(r"^(.*?)([,:\s]+)([^\W\d_]+)([\s!?.]*)$", text)
        if m_end:
            head = m_end.group(1).strip()
            sep = m_end.group(2)
            w_raw = m_end.group(3)
            punct = m_end.group(4)
            w_low = w_raw.lower()

            prev_word_m = re.search(r"([^\W\d_]+)[^\w]*$", head)
            prev_word = prev_word_m.group(1).lower() if prev_word_m else ""

            GREETING_WORDS = {"привет", "здравствуйте", "здорово", "доброе", "добрый", "салют", "пока"}
            # If preceded by a noun without a comma, it's a possessive genitive (e.g. 'машина шефа', 'дом босса')
            is_possessive = ("," not in sep) and self._is_noun(prev_word) and (prev_word not in GREETING_WORDS)
            # If preceded by an adjective/pronoun without a comma, it modifies the noun (e.g. 'мой командир', 'отличный парень')
            is_modified = ("," not in sep) and self._is_modifier(prev_word)
            # Check if preceded by a transitive verb (direct object: 'спасли босса', 'убил командира')
            is_transitive = ("," not in sep) and self._is_transitive_verb(prev_word)

            # Check if transitive verb precedes an intervening adverb (e.g. 'я не вижу здесь босса')
            if not is_transitive and ("," not in sep) and prev_word in {"здесь", "тут", "там", "сейчас", "больше", "вовсе"}:
                words_before = [w.lower() for w in re.findall(r"[^\W\d_]+", head)]
                if len(words_before) >= 2:
                    verb_candidate = words_before[-2]
                    parses = self.morph.parse(verb_candidate)
                    if any(p.tag.POS == "VERB" and "tran" in p.tag and "indc" in p.tag for p in parses):
                        is_transitive = True

            if not is_possessive and not is_modified and not is_transitive and prev_word not in NON_VOCATIVE_PREPS:
                if w_low in VOCATIVE_MAP:
                    rep = self._apply_case(w_raw, VOCATIVE_MAP[w_low])
                    sep_clean = ", " if "," not in sep else sep
                    text = f"{head}{sep_clean}{rep}{punct}"
                elif w_low in NOMINATIVE_VOCATIVES and "," not in sep:
                    text = f"{head}, {w_raw}{punct}"

        return text

    def clean_subtitle_typography(self, text: str) -> str:
        """
        Specialized subtitle typography formatter for fast-paced video shorts.
        - Strips dangling trailing commas, colons, semicolons, and hyphens at the end of chunks.
        - Strips dangling commas right before manual line breaks (\\N).
        - Strictly preserves legitimate commas inside short subtitle cards (e.g. 'Да, конечно', 'Стой, стреляю!').
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        # 1. Strip dangling commas, semicolons, colons, hyphens before \N
        text = re.sub(r"[,;:\-—–]+(?=\s*\\N)", "", text)

        # 2. Strip dangling commas, semicolons, colons, hyphens at the end of the subtitle
        text = re.sub(r"[,;:\-—–]+\s*$", "", text)

        return text

    def clean_and_correct(self, text: str, is_subtitle_chunk: bool = True) -> str:
        """
        Performs punctuation sanitation, grammatical agreement corrections,
        vocative normalization, action phonetics, blogger promo stripping,
        and subtitle typography polishing while preserving word casing throughout.
        """
        if not text or not isinstance(text, str):
            return "" if text is None else str(text)

        # 1. Strip blogger promotional voiceovers, CTAs, and watermarks
        text = self.strip_blogger_promos(text)
        if not text:
            return ""

        # 2. Initial punctuation cleanup
        text = self.sanitize_punctuation(text)

        # 2.5. Apply persistent user custom dictionary rules
        text = self.apply_user_rules(text)

        # 3. Action phonetics corrections
        text = self.correct_action_phonetics(text)

        # 4. Vocatives normalization & proper punctuation
        text = self.correct_vocatives(text)

        # 5. Grammatical agreements (adjective/pronoun + noun)
        text = self.correct_agreements(text)

        # 6. Secondary punctuation cleanup
        text = self.sanitize_punctuation(text)

        # 7. Subtitle typography polish
        if is_subtitle_chunk:
            text = self.clean_subtitle_typography(text)

        return text

    def apply_user_rules(self, text: str) -> str:
        """Applies persistent user-defined word/phrase replacements from user_rules.json."""
        if not text:
            return text
        rules_path = os.path.join(os.path.dirname(__file__), "user_rules.json")
        if not os.path.exists(rules_path):
            rules_path = "user_rules.json"
        if os.path.exists(rules_path):
            try:
                import json
                with open(rules_path, "r", encoding="utf-8") as f:
                    rules = json.load(f)
                for old_val, new_val in rules.items():
                    if not old_val:
                        continue
                    pattern = re.compile(rf"\b{re.escape(old_val)}\b", re.IGNORECASE)
                    def _rep(m):
                        val = m.group(0)
                        if val.isupper():
                            return new_val.upper()
                        elif val.islower():
                            return new_val.lower()
                        elif val.istitle():
                            return new_val.capitalize()
                        return new_val
                    text = pattern.sub(_rep, text)
            except Exception:
                pass
        return text


def save_user_rule(old_word: str, new_word: str, rules_path: str = "user_rules.json") -> bool:
    """Saves a user replacement rule to user_rules.json."""
    old_clean = old_word.strip().lower()
    new_clean = new_word.strip()
    if not old_clean or not new_clean:
        return False
    data = {}
    if os.path.exists(rules_path):
        try:
            import json
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[old_clean] = new_clean
    try:
        import json
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    corrector = RussianGrammarCorrector()
    sample = "у тебя одно обойма?.."
    result = corrector.clean_and_correct(sample)
    print(f"Input : '{sample}'")
    print(f"Output: '{result}'")
