from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Union, List
import re


class Directive:
    def __init__(self, pattern: str, replacement: str, name: Union[str, None] = None):
        self.pattern = pattern
        self.replacement = replacement
        self.name = name


RST_DIRECTIVES: List[Directive] = [
    Directive(
        pattern=r'\.\. versionchanged:: (?P<version>\S+)(?P<end>$|\n)',
        replacement=r'*Changed in \g<version>*\g<end>'
    ),
    Directive(
        pattern=r'\.\. versionadded:: (?P<version>\S+)(?P<end>$|\n)',
        replacement=r'*Added in \g<version>*\g<end>'
    ),
    Directive(
        pattern=r'\.\. deprecated:: (?P<version>\S+)(?P<end>$|\n)',
        replacement=r'*Deprecated since \g<version>*\g<end>'
    ),
    Directive(
        pattern=r'\.\. warning::/g',
        replacement=r'**Warning**'
    ),
    Directive(
        pattern=r'\.\. seealso::(?P<short_form>.*)(?P<end>$|\n)',
        replacement=r'*See also*\g<short_form>\g<end>'
    ),
    Directive(
        pattern=r':ref:`(?P<label>[^<`]+?)\s*<(?P<ref>[^>`]+?)>`',
        replacement=r'\g<label>: `\g<ref>`'
    ),
    Directive(
        pattern=r'`(?P<label>[^<`]+?)(\n?)<(?P<url>[^>`]+)>`_+',
        replacement=r'[\g<label>](\g<url>)'
    ),
    Directive(
        pattern=r':mod:`(?P<label>[^`]+)`',
        replacement=r'`\g<label>`'
    ),
    Directive(
        pattern=r'\.\. currentmodule:: (?P<module>.+)(?P<end>$|\n)',
        replacement=''
    ),
    Directive(
        pattern=r':math:`(?P<latex>[^`]+?)`',
        # this will give $latex$, the second dollar is an escape character
        replacement=r'$\g<latex>$'
    ),
    Directive(
        pattern=r'\.\. highlight:: (?P<language>.+)(?P<end>$|\n)',
        replacement=r'',
        name='highlight'
    ),
    Directive(
        pattern=r'\.\. (code-block|productionlist)::(?P<language>.*)(?P<end>$|\n)',
        replacement=r'\g<end>',
        name='code-block'
    )
]


def _find_directive_pattern(name: str):
    return [
        directive for directive in RST_DIRECTIVES
        if directive.name == name
    ][0].pattern


HIGHLIGHT_PATTERN = _find_directive_pattern('highlight')
CODE_BLOCK_PATTERN = _find_directive_pattern('code-block')

_RST_SECTIONS = [
    'Parameters',
    'Returns',
    'See Also',
    'Examples',
    'Attributes',
    'Notes',
    'References'
]


def looks_like_rst(value: str) -> bool:
    # check if any of the characteristic sections (and the properly formatted underline) is there
    for section in _RST_SECTIONS:
        if (section + '\n' + '-' * len(section) + '\n') in value:
            return True
    for directive in RST_DIRECTIVES:
        if re.search(directive.pattern, value):
            return True
    # allow "text::" or "text ::" but not "^::$" or "^:::$"
    return re.search(r'(\s|\w)::\n', value) or '\n>>> ' in value


class IBlockBeginning(SimpleNamespace):
    """
    Line that does not belong to the code block and should be prepended and analysed separately
    """
    remainder: str


class IParser(ABC):

    @abstractmethod
    def can_parse(self, line: str) -> bool:
        pass

    @abstractmethod
    def initiate_parsing(self, line: str, current_language: str) -> IBlockBeginning:
        pass

    @abstractmethod
    def can_consume(self, line: str) -> bool:
        pass

    @abstractmethod
    def consume(self, line: str) -> None:
        pass

    @abstractmethod
    def finish_consumption(self, final: bool) -> str:
        pass

    follower: Union['IParser', None]


class BlockParser(IParser):
    enclosure = '```'
    follower = None
    _buffer: List[str]
    _block_started: bool

    def __init__(self):
        self._buffer = []
        self._block_started = False

    @abstractmethod
    def can_parse(self, line: str) -> bool:
        """
        All children should call _start_block in initiate_parsing() implementation.
        """
        pass

    @abstractmethod
    def initiate_parsing(
            self,
            line: str,
            current_language: str
    ) -> IBlockBeginning:
        pass

    def _start_block(self, language: str):
        self._buffer.append(self.enclosure + language)
        self._block_started = True

    @abstractmethod
    def can_consume(self, line: str) -> bool:
        pass

    def consume(self, line: str):
        if not self._block_started:
            raise ValueError('Block has not started')
        self._buffer.append(line)

    def finish_consumption(self, final: bool):
        # if the last line is empty (e.g. a separator of intended block), discard it
        if self._buffer[len(self._buffer) - 1].strip() == '':
            self._buffer.pop()
        self._buffer.append(self.enclosure + '\n')
        result = '\n'.join(self._buffer)
        if not final:
            result += '\n'
        self._buffer = []
        self._block_started = False
        return result


class IndentedBlockParser(BlockParser, ABC):
    _is_block_beginning: bool
    _block_indent_size: Union[int, None]

    def __init__(self):
        super(IndentedBlockParser, self).__init__()
        self._is_block_beginning = False

    def _start_block(self, language: str):
        super()._start_block(language)
        self._block_indent_size = None
        self._is_block_beginning = True

    def can_consume(self, line: str) -> bool:
        if self._is_block_beginning and line.strip() == '':
            return True
        return (len(line) > 0 and re.match(r'^\s', line[0])) or len(line) == 0

    def consume(self, line: str):
        if self._is_block_beginning:
            # skip the first empty line
            self._is_block_beginning = False
            if line.strip() == '':
                return
        if self._block_indent_size is None:
            self._block_indent_size = len(line) - len(line.lstrip())
        super().consume(line[self._block_indent_size:])

    def finish_consumption(self, final: bool) -> str:
        self._is_block_beginning = False
        self._block_indent_size = None
        return super().finish_consumption(final)


class PythonOutputBlockParser(BlockParser):
    def can_consume(self, line: str) -> bool:
        return line.strip() != '' and not line.startswith('>>>')

    def can_parse(self, line: str) -> bool:
        # cannot be initiated directly
        return False

    def initiate_parsing(self, line: str, current_language: str) -> IBlockBeginning:
        self._start_block('')
        self.consume(line)
        return IBlockBeginning(remainder='')


class PythonPromptCodeBlockParser(BlockParser):
    def can_parse(self, line: str) -> bool:
        return line.startswith('>>>')

    def initiate_parsing(self, line: str, current_language: str) -> IBlockBeginning:
        self._start_block('python')
        self.consume(line)
        return IBlockBeginning(remainder='')

    def can_consume(self, line: str) -> bool:
        return line.startswith('>>>') or line.startswith('...')

    def consume(self, line: str):
        super().consume(self._strip_prompt(line))

    def _strip_prompt(self, line: str) -> str:
        start = 4 if line.startswith('>>> ') or line.startswith('... ') else 3
        return line[start:]

    follower = PythonOutputBlockParser()


class DoubleColonBlockParser(IndentedBlockParser):

    def can_parse(self, line: str):
        # note: Python uses ' ::' but numpy uses just '::'
        return line.rstrip().endswith('::')

    def initiate_parsing(self, line: str, current_language: str):
        language = current_language
        if line.strip() == '.. autosummary::':
            language = ''
            line = ''
        else:
            line = re.sub(r'::$', '', line)

        self._start_block(language)
        return IBlockBeginning(remainder=line + '\n\n')


class MathBlockParser(IndentedBlockParser):
    enclosure = '$$'

    def can_parse(self, line: str):
        return line.strip() == '.. math::'

    def initiate_parsing(self, line: str, current_language: str):
        self._start_block('')
        return IBlockBeginning(remainder='')


class ExplicitCodeBlockParser(IndentedBlockParser):
    def can_parse(self, line: str) -> bool:
        return re.match(CODE_BLOCK_PATTERN, line) is not None

    def initiate_parsing(self, line: str, current_language: str) -> IBlockBeginning:
        match = re.match(CODE_BLOCK_PATTERN, line)
        self._start_block(match.group('language').strip() or current_language)
        return IBlockBeginning(remainder='')


BLOCK_PARSERS = [
    PythonPromptCodeBlockParser(),
    MathBlockParser(),
    ExplicitCodeBlockParser(),
    DoubleColonBlockParser()
]

RST_SECTIONS = {
    section: '\n' + section + '\n' + '-' * len(section)
    for section in _RST_SECTIONS
}

NBSP_INDENT = '    '


def rst_to_markdown(text: str):
    """
    Try to parse docstrings in following formats to markdown:
    - https://www.python.org/dev/peps/pep-0287/
    - https://www.python.org/dev/peps/pep-0257/
    - https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_numpy.html
    - https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html#literal-blocks

    It is intended to improve the UX while better the solutions at the backend
    are being investigated rather than provide a fully-featured implementation.

    Supported features:
    - code blocks:
      - PEP0257 (formatting of code with highlighting, formatting of output without highlighting)
      - after ::
      - production lists,
      - explicit code blocks
    - NumPy-like list items
    - external links (inline only)
    - as subset of paragraph-level and inline directives (which must fit into a single line)

    Arguments:
        text - the input docstring
    """
    language = 'python'
    markdown = ''
    active_parser: Union[IParser, None] = None
    lines_buffer: List[str] = []

    def flush_buffer():
        nonlocal lines_buffer
        lines = '\n'.join(lines_buffer)
        # rst markup handling
        for directive in RST_DIRECTIVES:
            lines = re.sub(directive.pattern, directive.replacement, lines)

        for (section, header) in RST_SECTIONS.items():
            lines = lines.replace(header, '\n#### ' + section + '\n')

        lines = lines.replace(NBSP_INDENT, '    ')
        lines_buffer = []
        return lines

    for line in text.split('\n'):
        trimmed_line = line.lstrip()

        if active_parser:
            if active_parser.can_consume(line):
                active_parser.consume(line)
            else:
                markdown += flush_buffer()
                markdown += active_parser.finish_consumption(False)
                if active_parser.follower:
                    active_parser = active_parser.follower
                    active_parser.initiate_parsing(line, language)
                else:
                    active_parser = None

        if not active_parser:
            # we are not in a code block now but maybe we enter start one?
            for parser in BLOCK_PARSERS:
                if parser.can_parse(line):
                    active_parser = parser
                    block_start = parser.initiate_parsing(line, language)
                    line = block_start.remainder
                    break

            # ok, we are not in any code block (it may start with the next line, but this line is clear - or empty)

            # lists handling:  items detection
            match = re.match(r'^(?P<argument>[^: ]+) : (?P<type>.+)$', trimmed_line)
            if match:
                line = '- `' + match.group('argument') + '`: ' + match.group('type') + ''

            # change highlight language if requested
            # this should not conflict with the parsers starting above
            # as the highlight directive should be in a line of its own
            highlight_match = re.search(HIGHLIGHT_PATTERN, line)
            if highlight_match and highlight_match.group('language').strip() != '':
                language = highlight_match.group('language').strip()

            lines_buffer.append(line)

    markdown += flush_buffer()
    # close off the code block - if any
    if active_parser:
        markdown += active_parser.finish_consumption(True)
    return markdown
