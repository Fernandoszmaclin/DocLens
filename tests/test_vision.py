import numpy as np

from doclens.vision import recognize


def test_reading_order_groups_fragments_on_same_line():
    class Reader:
        def readtext(self, image, **kwargs):
            return [
                ([[100, 9], [180, 9], [180, 28], [100, 28]], "direita", 0.9),
                ([[10, 11], [80, 11], [80, 30], [10, 30]], "esquerda", 0.9),
                ([[10, 55], [180, 55], [180, 75], [10, 75]], "linha seguinte", 0.9),
            ]

    blocks = recognize(np.zeros((100, 200, 3), dtype=np.uint8), Reader())
    assert [block["text"] for block in blocks] == ["esquerda", "direita", "linha seguinte"]
