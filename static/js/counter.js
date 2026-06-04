function isElementInViewport($el) {
    const rect = $el[0].getBoundingClientRect();
    return rect.bottom > 0 && rect.top < window.innerHeight;
}

function initCounterScroll() {
    const $counters = $(".counter-item");

    if ($counters.length === 0) return;

    function updateCounters() {
        $counters.each(function () {
            const $counter = $(this);
            if (isElementInViewport($counter) && !$counter.hasClass("counted")) {
                $counter.addClass("counted");
                const targetNumber = $counter.find(".odometer").data("number");
                $counter.find(".odometer").text(targetNumber);
            }
        });
    }

    // Throttle scroll event (mỗi 200ms)
    let timeout;
    $(window).on("scroll", function () {
        if (!timeout) {
            timeout = setTimeout(function () {
                updateCounters();
                timeout = null;
            }, 200);
        }
    });
    updateCounters();
}


$(document).ready(function () {
    if ($(".counter-scroll").length > 0) {
        initCounterScroll();
    }
});
