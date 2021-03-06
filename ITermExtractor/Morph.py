import logging
import re
from operator import itemgetter
from pyxdameraulevenshtein import normalized_damerau_levenshtein_distance_ndarray
from typing import List, Tuple  # TODO PEP 484 & type checks

import numpy as np
import pymorphy2

import helpers
from ITermExtractor.Structures.Case import Case, CaseNameConverter
from ITermExtractor.Structures.PartOfSpeech import PartOfSpeech, POSNameConverter
from ITermExtractor.Structures.WordStructures import TaggedWord, Collocation, non_whitespace_separators, Separator

LENGTH_LIMIT_PER_PROCESS = 200
DIST_THRESHOLD = 0.15
__MorphAnalyzer__ = pymorphy2.MorphAnalyzer()


def is_word_in_tuple_list(collocation: List[TaggedWord], check_word: str) -> bool:
    """
    осуществляет проверку наличия слова (check_word) в словосочетании
    checks if checked word is in collocation
    :param collocation: Tagged word list consisting of named tuples
    :param check_word: an argument to check
    :return: if word is in collocation or not

    >>> is_word_in_tuple_list([TaggedWord(word="огонь", pos=PartOfSpeech.noun, case=Case.nominative, normalized="огонь"), TaggedWord(word="артиллерии", pos=PartOfSpeech.noun, case=Case.genitive, normalized="артиллерия")], "артиллерией")
    True
    """
    if not isinstance(collocation, list) or len(collocation) == 0 or False in [isinstance(word, TaggedWord) for word in
                                                                               collocation]:
        raise TypeError("Необходим список слов с тегами")
    if not isinstance(check_word, str) or check_word == "":
        raise TypeError("Необходимо слово для проверки")

    flag = True
    for word in collocation:
        flag |= check_word == word.word
        if flag:
            break
    return flag


def is_identical_word(word1: str or TaggedWord, word2: str or TaggedWord) -> bool:
    """
    Compares 2 words and returns true if these are the same word in different cases
    :type word1: str or TaggedWord
    :type word2: str or TaggedWord
    :param word1: word number 1
    :param word2: word number 2
    :return: if words are the same & differ from each other in cases

    >>> is_identical_word("огонь", "огня")
    True
    >>> is_identical_word("артиллерии", "артиллерии")
    True
    >>> is_identical_word("слово", "начало")
    False
    >>> is_identical_word("в начале было", "в начале были")
    Traceback (most recent call last):
    ...
    ValueError: Были переданы словосочетания
    >>> is_identical_word("парково-хозяйственный", "парково-хозяйственный")
    True
    >>> is_identical_word('', "огонь")
    False
    >>> is_identical_word("Синий", "огонь артиллерии")
    Traceback (most recent call last):
    ...
    ValueError: Были переданы словосочетания
    >>> is_identical_word("огонь артиллерии", "Синий")
    Traceback (most recent call last):
    ...
    ValueError: Были переданы словосочетания
    >>> is_identical_word(1, "в начале были")
    Traceback (most recent call last):
    ...
    TypeError: Требуется два строковых или TaggedWord аргумента
    >>> is_identical_word("123123", "в начале были")
    Traceback (most recent call last):
    ...
    ValueError: Были переданы словосочетания
    >>> is_identical_word("артиллерия", "sda123123")
    Traceback (most recent call last):
    ...
    ValueError: Недопустимое значение аргументов. Необходимы символьные строки
    """
    is_tagged_words = isinstance(word1, TaggedWord) and isinstance(word2, TaggedWord)
    is_strs = isinstance(word1, str) and isinstance(word2, str)
    if not (is_strs or is_tagged_words):
        raise TypeError("Требуется два строковых или TaggedWord аргумента")
    if is_strs:
        if word1 == "" or word2 == "":
            return False
        if word1.count(' ') >= 1 or word2.count(' ') >= 1:
            raise ValueError("Были переданы словосочетания")
        if not (helpers.is_correct_word(word1) and helpers.is_correct_word(word2)):
            raise ValueError("Недопустимое значение аргументов. Необходимы символьные строки")
        word1 = word1.lower()
        word2 = word2.lower()

    result = word1 == word2
    if not result:
        if is_strs:
            word1_parse_info = tag_collocation(word1)[0]
            word2_parse_info = tag_collocation(word2)[0]
            result = word1_parse_info.normalized == word2_parse_info.normalized
        else:
            result = word1.normalized == word2.normalized
    return result


def get_main_word(collocation: List[TaggedWord]) -> str:
    """
    Получает главное слово в словосочетании
    :param collocation: словосочетание с тегами
    :return: главное слово в словосочетании, строка

    >>> get_main_word([TaggedWord(word="огня", pos=PartOfSpeech.noun, case=Case.genitive, normalized="огонь"), TaggedWord(word="артиллерии", pos=PartOfSpeech.noun, case=Case.genitive, normalized="артиллерия")])
    'огня'
    >>> get_main_word([TaggedWord(word="огонь", pos=PartOfSpeech.noun, case=Case.nominative, normalized="огонь"), TaggedWord(word="артиллерии", pos=PartOfSpeech.noun, case=Case.genitive, normalized="артиллерия")])
    'огонь'
    >>> get_main_word([TaggedWord(word="парково-хозяйственный", pos=PartOfSpeech.adjective, case=Case.nominative, normalized="парково-хозяйственный"), TaggedWord(word="день", pos=PartOfSpeech.noun, case=Case.nominative, normalized="день")])
    'день'
    >>> get_main_word([TaggedWord(word="слушать", pos=PartOfSpeech.verb, case=Case.none, normalized="слушать"), TaggedWord(word="громко", pos=PartOfSpeech.adverb, case=Case.none, normalized="громко")])
    Traceback (most recent call last):
    ...
    ValueError: Словосочетания с глаголами и наречиями не поддерживаются
    """
    check_list = [isinstance(word, TaggedWord) for word in collocation]
    if not isinstance(collocation, list) or len(collocation) == 0 or not all(check_list):
        return ""

    pos = [word.pos for word in collocation]

    flag = not (PartOfSpeech.verb in pos and PartOfSpeech.adverb in pos)
    if not flag:  # TODO пока отрабатывать лишь словосочетания сущ+сущ и прил+сущ
        raise ValueError("Словосочетания с глаголами и наречиями не поддерживаются")

    result = ""
    if len(collocation) == 1 and PartOfSpeech.noun in pos:
        result = collocation[0].word
    else:
        nouns = pos.count(PartOfSpeech.noun)
        if nouns == 1:
            for w in collocation:
                if w.pos == PartOfSpeech.noun:
                    result = w.word
        else:
            for w in collocation:
                if w.case == Case.nominative or w.case == Case.accusative:
                    result = w.word
                    break
            if result == '':
                nouns = [word for word in collocation if word.pos == PartOfSpeech.noun]
                if len(nouns) != 0:
                    result = nouns[0].word
    return result
    # получаем список частей речи в словосоч. Если одно сущ, остальные прилагательные
    # если сущ+сущ, то или в  и.п., или первое


# TODO при обнаружении в тексте 2х терминов в разных падежах - приводить к одному
# определение из 2, Какое из них в именительном падеже


def is_identical_collocation(collocation1: str, collocation2: str) -> bool:
    """
    Compares 2 collocations and returns true if they represents the same concept but in different cases
    :param collocation1:
    :param collocation2:
    :return: bool value

    >>> is_identical_collocation('огонь артиллерии', 'огня артиллерии')
    True
    >>> is_identical_collocation('', '')
    Traceback (most recent call last):
    ...
    ValueError: Необходимы словосочетания
    >>> is_identical_collocation('plešemo', 'mi plešemo')
    Traceback (most recent call last):
    ...
    ValueError: Необходимы словосочетания
    >>> is_identical_collocation('mi plešemo', 'plešemo')
    Traceback (most recent call last):
    ...
    ValueError: Необходимы словосочетания
    >>> is_identical_collocation('парково-хозяйственный день', 'парково-хозяйственный 6 день')
    Traceback (most recent call last):
    ...
    ValueError: Слова в словосочетаниях должны состоять из букв
    >>> is_identical_collocation('парково-хозяйственный день', 'парково-хо99зяйственный6 день')
    Traceback (most recent call last):
    ...
    ValueError: Слова в словосочетаниях должны состоять из букв
    >>> is_identical_collocation('минометных дивизионов', 'и дивизионов')
    False
    """

    if not (isinstance(collocation1, str) and isinstance(collocation2, str)):
        raise TypeError("Ошибка типов. Необходимы строки")
    words_coll1 = collocation1.split()
    words_coll2 = collocation2.split()
    if len(words_coll1) <= 1 or len(words_coll2) <= 1:
        raise ValueError("Необходимы словосочетания")
    val_check = [helpers.is_correct_word(word) for word in words_coll1 + words_coll2]
    if False in val_check:
        raise ValueError("Слова в словосочетаниях должны состоять из букв")

    if collocation1 == collocation2:
        return True
    word_count_check = len(words_coll1) == len(words_coll2)
    if not word_count_check:
        return False

    collocation1_tagged = tag_collocation(collocation1)
    collocation2_tagged = tag_collocation(collocation2)
    main_word_1 = get_main_word(collocation1_tagged)
    main_word_2 = get_main_word(collocation2_tagged)

    if not is_identical_word(main_word_1, main_word_2):
        return False
    is_identical = True
    for i in range(0, len(collocation1_tagged)):
        is_identical = is_identical and is_identical_word(collocation1_tagged[i].word, collocation2_tagged[i].word)
        if not is_identical:
            break

    return is_identical


def is_identical_collocation_q(collocation1: List[TaggedWord], collocation2: List[TaggedWord]) -> bool:
    """
    Ускоренная и упрощенная версия is_identical_collocation()
    :param collocation1: словосочетание с тегами
    :param collocation2: словосочетание с тегами
    :return: bool value
    """

    if not (isinstance(collocation1, list) and isinstance(collocation2, list)):  # List[TaggedWord]
        raise TypeError("Ошибка типов. Необходимы словосочетания упакованные в List[TaggedWord]")
    if len(collocation1) < 1 or len(collocation2) < 1:  # TODO condition
        raise ValueError(
            "Необходимы словосочетания:\n {0} ({1})\n {2} ({3})".format(collocation1, len(collocation1), collocation2,
                                                                        len(collocation2)))

    if collocation1 == collocation2:
        return True
    if len(collocation1) != len(collocation2):
        return False

    main_word_1 = get_main_word(collocation1)
    main_word_2 = get_main_word(collocation2)

    comparison_result = False
    try:
        comparison_result = is_identical_word(main_word_1, main_word_2)
    except ValueError as e:
        pass
        # TODO suppressed log output
        # logging.error("Проверка двух слов ('{0}' и '{1}') завершилась ошибкой\n{2}".format(main_word_1, main_word_2, e))
    if not comparison_result:
        return False
    is_identical = True
    for i in range(0, len(collocation1)):
        is_identical = is_identical and collocation1[i].normalized == collocation2[i].normalized
        if not is_identical:
            break

    return is_identical


def binary_identity_check(collocation: List[TaggedWord], collocation_list: List[Tuple[int, List[TaggedWord]]]) -> List[
    Tuple[int, bool]]:  # индекс, True/False
    """
    Проверяет наличие словосочетания в списке бинарным поиском
    :param collocation: словосочетание
    :param collocation_list: список словосочетаний с индексами
    :return: результирующий список (индекс, найдено/не найдено)

    >>> collocation_info = [tag_collocation(i) for i in ['огонь артиллерии', 'вызов огня артиллерии', 'огня артиллерии большой мощности', 'огня артиллерии']]
    >>> binary_identity_check(collocation_info[0], list(enumerate(collocation_info)))
    [(0, True), (1, False), (2, False), (3, True)]
    """
    if len(collocation_list) == 1:
        tmp = collocation_list[0]
        return [(tmp[0], is_identical_collocation_q(collocation, tmp[1]))]
    else:
        middle_index = int(len(collocation_list) / 2)
        first_half = collocation_list[:middle_index]
        second_half = collocation_list[middle_index:]
        first_result = binary_identity_check(collocation, first_half)
        second_result = binary_identity_check(collocation, second_half)
        result = [] + first_result + second_result
        return result
        # LENGTH_LIMIT_PER_PROCESS
    # [(is_identical_collocation_q(collocation, coll[1]), coll[0], coll[1]) for coll in enumerate(collocation_list)]


def in_collocation_list_var(collocation: str, collocation_list: List[str]) -> Tuple[bool, str]:
    # TODO мб возвращать термин в нормальной форме, если попадается в collocation? mainword в и.п.
    # TODO overcomplicated
    """
    Осуществляет проверку наличия словосочетания с списке, учитывая падеж
    :param collocation: словосочетание
    :param collocation_list: список словосочетаний
    :return: да/нет + идентичный элемент

    >>> in_collocation_list_var('огонь артиллерии', ['основная задача', 'стрелкового оружия', 'огня артиллерии'])
    (True, 'огня артиллерии')
    >>> in_collocation_list_var('огонь артиллерии', ['основная задача', 'стрелкового оружия', 'артиллерийская подготовка'])
    (False, None)
    >>> in_collocation_list_var('', ['основная задача', 'стрелкового оружия', 'огня артиллерии'])
    Traceback (most recent call last):
    ...
    ValueError: Необходимы словосочетания
    >>> in_collocation_list_var('огонь артиллерии', [])
    (False, None)
    >>> in_collocation_list_var('и дивизионов', ['командующий войсками армии', 'стрелковых дивизий минометных дивизионов', 'минометных дивизионов',  'боевому применению'])
    (False, None)
    """

    if not isinstance(collocation, str):
        raise TypeError("Ошибка типов. Необходимо словосочетание")
    if not isinstance(collocation_list, list):
        raise TypeError("Ошибка типов. Необходим список словосочетаний")

    words_coll = collocation.split()
    if len(collocation_list) == 0:
        return False, None

    val_check = [helpers.is_correct_word(word) for word in words_coll]
    val_check_coll = [
        isinstance(coll, str) and False not in [helpers.is_correct_word(coll_word) for coll_word in coll.split()]
        for coll in collocation_list]
    if False in val_check or False in val_check_coll:
        raise ValueError("Слова в словосочетаниях должны состоять из букв")

    flag = collocation in collocation_list
    found_index = -1
    collocation_list.sort()  # key=lambda x: x
    if not flag:
        identity_check = [is_identical_collocation(collocation, coll) for coll in collocation_list]
        flag = True in identity_check
        if flag:
            found_index = identity_check.index(True)
    return flag, collocation_list[found_index] if found_index > -1 else None


def count_includes(collocation: List[TaggedWord], collocation_list: List[List[TaggedWord]]) -> List[
    Tuple[int, List[TaggedWord]]]:
    """
    Осуществляет проверку наличия словосочетания с списке, учитывая падеж
    :param collocation: словосочетание
    :param collocation_list: список словосочетаний
    :return: информацию о включениях (индекс, Слово)

    >>> collocation_info = [tag_collocation(i) for i in ['огонь артиллерии', 'вызов огня артиллерии', 'огня артиллерии большой мощности', 'огня артиллерии']]
    >>> count_includes(collocation_info[0], collocation_info)  # doctest: +ELLIPSIS
    [(0, [TaggedWord(word='огонь', ...), TaggedWord(word='артиллерии', ...)]), (3, [TaggedWord(word='огня', ...), TaggedWord(word='артиллерии', ...)])]
    """
    # TODO more examples @doctest
    if not isinstance(collocation, list):  # TODO как провернуть эту проверку типов List[TaggedWord]?
        raise TypeError("Ошибка типов. Необходимо словосочетание")
    if not isinstance(collocation_list, list):
        raise TypeError("Ошибка типов. Необходим список словосочетаний")

    # flag = collocation in collocation_list
    # identity_check = [(is_identical_collocation_q(collocation, coll[1]), coll[0], coll[1]) for coll in enumerate(collocation_list)]  # True/False, index, collocation
    identity_check = binary_identity_check(collocation, list(enumerate(collocation_list)))
    found_matches = [(id_tuple[0], collocation_list[id_tuple[0]]) for id_tuple in identity_check if id_tuple[1]]
    return found_matches


def tag_word(word: str) -> TaggedWord:
    """
    Слову ставит в соответствие тег
    :param word: исходное слово
    :return: слово + тег
    """
    is_word_valid = word.isalpha() or word.find('-') > 0
    validity_check = is_word_valid
    reg_word_symbols = '[a-zA-Zа-яА-Я-]{1,}'
    if not is_word_valid:
        symbol_check = [symbol.isalpha() or symbol == '-' for symbol in word]
        if len(symbol_check) == 0:
            validity_check = False
        else:
            validity_check = symbol_check.count(True) / len(symbol_check) >= 0.7
            if validity_check:
                parts = re.findall(reg_word_symbols, word)
                validity_check = len(parts) == 1
                word = parts[0]

    if not validity_check:
        return None

    parse_info = __MorphAnalyzer__.parse(word)
    base_element = parse_info[0]
    if len(parse_info) > 1:
        max_match_score = max(parse_info, key=itemgetter(3)).score
        max_score_elements = list(filter(lambda x: x.score == max_match_score, parse_info))
        include_same_pos = all([element.tag.POS == base_element.tag.POS for element in max_score_elements])
        if len(max_score_elements) > 1 and not include_same_pos:
            max_score_elements = list(sorted(parse_info, key=itemgetter(1)))  # 'tag'
            base_element = max_score_elements[0]

    pos = PartOfSpeech.noun
    case = Case.none
    normalized = base_element.word
    try:
        pos = POSNameConverter.to_enum(str(base_element.tag.POS))
        case = CaseNameConverter.to_enum(str(base_element.tag.case))
        normalized = base_element.normal_form
    except ValueError as e:
        logging.error("Ошибка при распознании словоформы слова \"{0}\", [{1}, {2}]\n{3}".format(word, pos, case, e))
        if pos is "":
            return None
        if case is None:
            case = Case.none
    result = TaggedWord(word=word, pos=pos, case=case, normalized=normalized)
    return result


def tag_collocation(collocation: str) -> List[TaggedWord and Separator]:  # TODO test
    """
    Присваивает каждому слову в словосочетании метки части речи и падежа
    :param collocation: словосочетание
    :return: размеченный список слов
    """
    words = collocation.split()
    tagged_words = []
    for word in words:

        existing_separators = [(s, word.find(s)) for s in non_whitespace_separators if s in word]
        existing_separators = sorted(existing_separators, key=itemgetter(1))  # sort by position in a word
        if len(existing_separators) > 0:
            separatorless_word = word.strip(non_whitespace_separators)
            word_position = word.find(separatorless_word)
            tagged_word = tag_word(separatorless_word)

            preceding_separators = [Separator(symbol=s[0]) for s in existing_separators if s[1] < word_position]
            following_separators = [Separator(symbol=s[0]) for s in existing_separators if s[1] > word_position]

            if len(preceding_separators) != 0 and len(following_separators) != 0 and tagged_word is None:
                continue

            tagged_words += preceding_separators
            tagged_words.append(tagged_word)
            tagged_words += following_separators
        else:
            tagged_word = tag_word(word)
            if tagged_word is not None:
                tagged_words.append(tagged_word)

    return tagged_words


# @deprecated
def get_collocation_normal_form_old(collocations: List[List[TaggedWord]]) -> int:
    """
    Из перечня словосочетаний выбирает словосочетание, находящееся в нормальной форме
    Используется в случаях, когда необходимо выявить нормальную форму из списка словосочетаний
    ('огонь артиллерии', 'огня артиллерии') -> 'огонь артиллерии'
    Возвращает индекс
    :param collocations: перечень словосочетаний
    :return: индекс
    """
    index = -1
    for i in range(len(collocations)):
        main_word = get_main_word(collocations[i])
        if main_word == '':
            continue
        main_word_tagged_l = [word for word in collocations[i] if word.word == main_word]
        main_word_tagged = main_word_tagged_l[0] if len(main_word_tagged_l) > 0 else None
        if main_word_tagged is not None and (
                main_word_tagged.case == Case.nominative or main_word_tagged.word == main_word_tagged.normalized):
            index = i
            break
    return index


def get_biword_coll_normal_form(collocation: List[TaggedWord]) -> str:
    """
    Нормальная форма словосочетания из 2 слов 
    :param collocation: 
    :return: 
    """
    if len(collocation) != 2:
        return str()
    for i in range(len(collocation)):
        word = collocation[i]
        if isinstance(word, str):
            logging.warning('В словаре уже отпарсенных слов не нашлось \'{0}\''.format(word))
            collocation[i] = tag_word(word)

    main_word = get_main_word(collocation)
    normalized_collocation = []
    for word in collocation:
        if word.word == main_word or word.pos == PartOfSpeech.adjective:
            normalized_collocation.append(word.normalized)
        else:
            parse_info = __MorphAnalyzer__.parse(word.word)
            # the_word = list(filter(lambda o: CaseNameConverter.to_name(word.case) == o.tag.case, parse_info))[0]
            the_word = next(iter(filter(lambda o: CaseNameConverter.to_name(word.case) == o.tag.case, parse_info)),
                            None)
            if the_word is None:
                print('why? Было передано отпарсенное слово с неверным падежом?! {0}, чр {1}, п. {2}'
                      .format(word.word, word.pos, word.case))
                lexeme = next(iter(parse_info)).word
            else:
                lexeme = the_word.inflect({'gent'}).word
            normalized_collocation.append(lexeme)
    return ' '.join(normalized_collocation)


def get_collocation_normal_form(pnormal_form: str, collocations: List[Collocation], main_word: str) -> int:
    """
    Из перечня словосочетаний выбирает словосочетание, находящееся в нормальной форме
    Используется в случаях, когда необходимо выявить нормальную форму из списка словосочетаний
    ('огонь артиллерии', 'огня артиллерии') -> 'огонь артиллерии'
    Возвращает индекс
    :param main_word: главное слово в словосочетании
    :param pnormal_form: псевдонормальная форма
    :param collocations: перечень словосочетаний
    :return: индекс
    """
    if 'ё' in pnormal_form.lower():
        main_word = main_word.replace('ё', 'е')
        pnormal_form = pnormal_form.replace('ё', 'е')
        for c in collocations:
            c.collocation = c.collocation.replace('ё', 'е')
    forms = np.array([c.collocation for c in collocations])
    distances = normalized_damerau_levenshtein_distance_ndarray(pnormal_form, forms)
    indices = [(i, e) for i, e in enumerate(distances)
               if e - min(distances) <= DIST_THRESHOLD and main_word in collocations[i].collocation]
    if len(indices) > 1:  # TODO какие-то доп проверки?
        indices = sorted(indices, key=itemgetter(1))
    index = next(iter(indices)) if len(indices) > 0 else -1  # indices[0]
    if index == -1:
        logging.error("Что-то при выводе в лог случилось {0}".format(index, forms))
        return index
    return index[0]


def replace_main_word(collocation: Collocation, main_word: str) -> Collocation:
    if main_word not in collocation.pnormal_form or main_word in collocation:
        return collocation
    # number of word
    regular_phrase = collocation.collocation.split(' ')
    pn_phrase = collocation.pnormal_form.split(' ')
    for i in range(len(regular_phrase)):
        if pn_phrase[i] == main_word:
            regular_phrase[i] = main_word
            break
    new_coll = ' '.join(regular_phrase)
    return Collocation(new_coll, collocation.wordcount, 0, collocation.pnormal_form, collocation.llinked,
                       collocation.id)


# @NotImplemented
def get_normal_form(collocation: List[TaggedWord]) -> str:
    if not isinstance(collocation, list):
        raise TypeError("Аргумент должен быть списком слов")
    if len(collocation) == 0:
        return str()
    if len(collocation) == 1:
        return collocation[0].normal_form
    main_word = get_main_word(collocation)
    for word in collocation:
        if word == main_word:
            pass
        parse_info = __MorphAnalyzer__.parse(word)
        the_word = list(filter(lambda o: CaseNameConverter.to_name(word.case) == o.tag.case, parse_info))[0]
        the_word.inflect({'gent'})
    # candidate_term TaggedWord


def make_substrs(collocation: str) -> List[str]:  # TODO а почему артиллерия не может быть термином
    """
    Возвращает набор возможных подстрок
    :param collocation: словосочетание
    :return: подстроки

    >>> make_substrs('занятие огневых позиций')
    ['занятие огневых', 'огневых позиций']
    >>> make_substrs('районы огневых позиций')
    ['районы огневых', 'огневых позиций']
    >>> make_substrs('состав группы обеспечения')
    ['состав группы', 'группы обеспечения']
    >>> make_substrs('распределение построения боевых порядков')
    ['распределение построения боевых', 'построения боевых порядков', 'распределение построения', 'построения боевых', 'боевых порядков']
    """
    if not isinstance(collocation, str):
        raise TypeError('Требуется строка')
    if collocation == '':
        return ''
    words = [word for word in collocation.split()]  # TODO different 2/3/4w combinations
    substrings = []
    for wcount in range(len(words) - 1, 1, -1):
        for j in range(0, len(words) - wcount + 1):
            substrings.append(' '.join(words[j:j + wcount]))
    return substrings


def get_longer_terms(line: Collocation, longer_grams: List[Collocation], dictionary: List[TaggedWord]) -> List[
    Collocation]:
    """
    Возвращает перечень кандидатов, в которых содержится строка line
    :param line:
    :param longer_grams:
    :param dictionary:
    :return:

    >>> grams = [Collocation(collocation='распределение построения боевых', wordcount=3, freq=1), Collocation(collocation='построения боевых порядков', wordcount=3, freq=1), Collocation(collocation='распределение построения', wordcount=2, freq=1), Collocation(collocation='распределение построения боевых порядков', wordcount=4, freq=1)]
    >>> dictionary = [TaggedWord(word='построения', pos=PartOfSpeech.noun, case=Case.genitive, normalized='построениe'), TaggedWord(word='боевых', pos=PartOfSpeech.adjective, case=Case.genitive, normalized='боевой'), TaggedWord(word='порядков', pos=PartOfSpeech.noun, case=Case.genitive, normalized='порядок'), TaggedWord(word='распределение', pos=PartOfSpeech.noun, case=Case.nominative, normalized='распределение'), TaggedWord(word='боевой', pos=PartOfSpeech.noun, case=Case.nominative, normalized='боевой'), TaggedWord(word='порядок', pos=PartOfSpeech.noun, case=Case.nominative, normalized='порядок')]
    >>> get_longer_terms(Collocation(collocation='боевой порядок', wordcount=2, freq=1), grams, dictionary)
    [collocation(collocation='построения боевых порядков', wordcount=3, freq=1), collocation(collocation='распределение построения боевых порядков', wordcount=4, freq=1)]
    """
    tagged_line = assign_tags(line, dictionary)
    longer_terms = []
    for gram in longer_grams:
        possible_identic_lines = [substr for substr in make_substrs(gram.collocation) if
                                  len(substr.split(' ')) == line.wordcount]
        tagged_possible_identic_lines = [assign_tags(l, dictionary) for l in possible_identic_lines]
        try:
            id_check = [is_identical_collocation_q(tagged_line, l) for l in tagged_possible_identic_lines]
        except Exception as e:
            # logging.error("Ошибка при проверке {0} и {1},\n а именно {2}".format(line, gram, e))2
            # TODO suppressed log output
            # TODO use traceback module
            continue
        if True in id_check:
            longer_terms.append(gram)
    return longer_terms


def assign_tags(phrase: str or Collocation, dictionary: List[TaggedWord]) -> List[TaggedWord]:
    """
    Распределяет теги из словаря словам из словосочетания
    :param phrase:
    :param dictionary:
    :return: словосочетания с тегами
    >>> dictionary = [TaggedWord(word='построения', pos=PartOfSpeech.noun, case=Case.genitive, normalized='построениe'), TaggedWord(word='боевых', pos=PartOfSpeech.adjective, case=Case.genitive, normalized='боевой'), TaggedWord(word='порядков', pos=PartOfSpeech.noun, case=Case.genitive, normalized='порядок'), TaggedWord(word='распределение', pos=PartOfSpeech.noun, case=Case.nominative, normalized='распределение'), TaggedWord(word='боевой', pos=PartOfSpeech.noun, case=Case.nominative, normalized='боевой'), TaggedWord(word='порядок', pos=PartOfSpeech.noun, case=Case.nominative, normalized='порядок')]
    >>> assign_tags('боевой порядок', dictionary)
    [TaggedWord(word='боевой', pos=<PartOfSpeech.noun: (1, 'S существительное (яблоня, лошадь, корпус, вечность)')>, case=<Case.nominative: (1, 'именительный')>, normalized='боевой'), TaggedWord(word='порядок', pos=<PartOfSpeech.noun: (1, 'S существительное (яблоня, лошадь, корпус, вечность)')>, case=<Case.nominative: (1, 'именительный')>, normalized='порядок')]

    """
    # TODO дубликаты c большим словарем
    if not (isinstance(phrase, str) or isinstance(phrase, Collocation)):
        raise TypeError("Передан аргумент неверного типа")
    is_str = isinstance(phrase, str)
    if is_str:
        raw_words = phrase.split(' ')
    else:
        raw_words = phrase.collocation.split(' ')

    tagged_collocation = [word for word in dictionary if word.word in raw_words]
    return tagged_collocation


def find_candidate_by_id(collocation_list: List[Collocation], cid: int):
    results = [collocation for collocation in collocation_list if collocation.id == cid]
    result = results[0] if len(results) > 0 else None
    if result is None:
        collocation_dict = dict([(r.id, r) for r in collocation_list])
        collocation_with_links = list(filter(lambda x: len(x.llinked) > 0, collocation_list))
        link_integrity_checks = [all(link in collocation_dict for link in p.llinked) for p in collocation_with_links]
        flag = all(link_integrity_checks)
        logging.debug(
            "----> Фраза по id (#{0}) не найдена, все ли в порядке со ссылками в списке: {1}, а хоть что-то: {2}".format(
                cid, flag, True in link_integrity_checks))
    return result
