
from markdown_engine.loader import MarkdownLoader

def test_loader(tmp_path):
    p=tmp_path/'a.md'
    p.write_text('# test')
    assert 'test' in MarkdownLoader().load(str(p))
