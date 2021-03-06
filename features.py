import re
from nltk.stem.porter import PorterStemmer
from nltk import word_tokenize


def tokenize(text):
    text = text.lower()
    tokens = word_tokenize(text)
    stems = []
    for item in tokens:
        stems.append(PorterStemmer().stem(item))
    return stems


def tokenize_2(text):
    text = text.lower()
    text = re.sub('[^a-zA-Z]+', ' ', text)
    tokens = word_tokenize(text)
    stems = []
    for item in tokens:
        stems.append(PorterStemmer().stem(item))
    return stems
