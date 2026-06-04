gsap.registerPlugin(ScrollTrigger);
(function ($) {
    ("use strict");

    /* animation_text
  -------------------------------------------------------------------------*/
    var animation_text = function () {
        if ($(".split-text").length > 0) {
            var st = $(".split-text");
            if (st.length === 0) return;
            gsap.registerPlugin(SplitText);
            st.each(function (index, el) {
                const $el = $(el);
                const $target =
                    $el.find("p, a").length > 0 ? $el.find("p, a")[0] : el;
                const hasClass = $el.hasClass.bind($el);
                const pxl_split = new SplitText($target, {
                    type: "words, chars, lines",
                    lineThreshold: 0.5,
                    wordsClass: "word",
                    linesClass: "split-line",
                });

                var gradientChars = st.find(".text-gradient > .word > *");
                var offset = 0;

                gradientChars.each(function (i, char) {
                    const _char = $(char);
                    const parent = _char.parent();
                    _char.css(
                        "background-size",
                        parent.outerWidth() + "px 100%"
                    );
                    offset += _char.prev().outerWidth() || 0;
                    _char.css(
                        "background-position",
                        parent.outerWidth() - offset + "px 0%"
                    );
                });
                let split_type_set = pxl_split.chars;
                gsap.set($target, { perspective: 400 });
                const settings = {
                    scrollTrigger: {
                        trigger: $target,
                        start: "top 86%",
                    },
                    duration: 0.9,
                    stagger: 0.02,
                    ease: "power3.out",
                };
                if (hasClass("effect-fade")) {
                    settings.opacity = 0;
                }
                if (hasClass("effect-right")) {
                    settings.opacity = 0;
                    settings.x = "50";
                }
                if (hasClass("effect-left")) {
                    settings.opacity = 0;
                    settings.x = "-50";
                }
                if (hasClass("effect-up")) {
                    settings.opacity = 0;
                    settings.y = "80";
                }
                if (hasClass("effect-down")) {
                    settings.opacity = 0;
                    settings.y = "-80";
                }
                if (hasClass("effect-rotate")) {
                    settings.opacity = 0;
                    settings.rotateX = "50deg";
                }
                if (hasClass("effect-scale")) {
                    settings.opacity = 0;
                    settings.scale = "0.5";
                }
                if (
                    hasClass("split-lines-transform") ||
                    hasClass("split-lines-rotation-x")
                ) {
                    pxl_split.split({
                        type: "lines",
                        lineThreshold: 0.5,
                        linesClass: "split-line",
                    });
                    split_type_set = pxl_split.lines;
                    settings.opacity = 0;
                    settings.stagger = 0.5;
                    if (hasClass("split-lines-rotation-x")) {
                        settings.rotationX = -120;
                        settings.transformOrigin = "top center -50";
                    } else {
                        settings.yPercent = 100;
                        settings.autoAlpha = 0;
                    }
                }
                if (hasClass("split-words-scale")) {
                    pxl_split.split({ type: "words" });
                    split_type_set = pxl_split.words;
                    split_type_set.forEach((elw, index) => {
                        gsap.set(
                            elw,
                            {
                                opacity: 0,
                                scale: index % 2 === 0 ? 0 : 2,
                                force3D: true,
                                duration: 0.1,
                                ease: "power3.out",
                                stagger: 0.02,
                            },
                            index * 0.01
                        );
                    });

                    gsap.to(split_type_set, {
                        scrollTrigger: {
                            trigger: el,
                            start: "top 86%",
                        },
                        rotateX: "0",
                        scale: 1,
                        opacity: 1,
                    });
                } else {
                    gsap.from(split_type_set, settings);
                }
            });
        }
    };

    /* scrolling_effect
  -------------------------------------------------------------------------*/
    var scrolling_effect = function () {
        if ($(".scrolling-effect").length > 0) {
            var st = $(".scrolling-effect");
            st.each(function (index, el) {
                var delayValue = $(el).attr("data-delay") || 0; // Lấy giá trị delay từ HTML hoặc mặc định là 0

                var settings = {
                    scrollTrigger: {
                        trigger: el,
                        start: "30px bottom",
                        end: "bottom bottom",
                        once: true,
                    },
                    duration: 0.9,
                    ease: "power3.out",
                    delay: parseFloat(delayValue), // Chuyển thành số
                };

                if ($(el).hasClass("effectRight")) {
                    settings.opacity = 0;
                    settings.x = "80";
                }
                if ($(el).hasClass("effectLeft")) {
                    settings.opacity = 0;
                    settings.x = "-80";
                }
                if ($(el).hasClass("effectBottom")) {
                    settings.opacity = 0;
                    settings.y = "100";
                }
                if ($(el).hasClass("effectTop")) {
                    settings.opacity = 0;
                    settings.y = "-80";
                }
                if ($(el).hasClass("effectZoomIn")) {
                    settings.opacity = 0;
                    settings.scale = 0.5;
                }
                if ($(el).hasClass("effectBounceUp")) {
                    settings.opacity = 0;
                    settings.y = "100";
                    settings.ease = "bounce.out";
                }

                gsap.from(el, settings);
            });
        }
    };

    /* scrollTransform
    -------------------------------------------------------------------------------------*/
    var scrollTransform = function () {
        const scrollTransformElements =
            document.querySelectorAll(".scroll-tranform");
        if (scrollTransformElements.length > 0) {
            scrollTransformElements.forEach(function (element) {
                const direction = element.dataset.direction || "up";
                const distance = element.dataset.distance || "10%";
                const rotateValue = element.dataset.rotate || "15";
    
                let animationProperty = {};
    
                switch (direction.toLowerCase()) {
                    case "left":
                        animationProperty.x = `-${distance}`;
                        break;
                    case "right":
                        animationProperty.x = `${distance}`;
                        break;
                    case "up":
                        animationProperty.y = `-${distance}`;
                        break;
                    case "down":
                        animationProperty.y = `${distance}`;
                        break;
                    case "rotate":
                        animationProperty.rotate = rotateValue;
                        break;
                    default:
                        animationProperty.y = `-${distance}`;
                }
    
                gsap.to(element, {
                    ...animationProperty,
                    scrollTrigger: {
                        trigger: element,
                        start: "top center",
                        end: "bottom top",
                        scrub: 2,
                    },
                });
            });
        }
    };
    

    /* animateImgScroll
    -------------------------------------------------------------------------------------*/
    var scrollBanners = function () {
        var st = $(".banner-stripe .text-container");
        st.each(function () {
            const settings = {
                scrollTrigger: {
                    trigger: this,
                    start: "top bottom",
                    end: "bottom top",
                    scrub: 1,
                    markers: false,
                },
                ease: "none",
            };
            if ($(this).hasClass("effect-left")) {
                settings.x = "-10%";
            }
            if ($(this).hasClass("effect-right")) {
                settings.x = "-10%";
            }
            gsap.to(this, settings);
        });
    };

    /* animationFooter
    -------------------------------------------------------------------------------------*/
    var animationFooter = function () {
        if ($(".footer-container").length) {
            var width = $(window).width();
            if (width > 991) {
                gsap.set(".footer-container", { yPercent: -50 });
                const uncover = gsap.timeline({ paused: true });
                uncover.to(".footer-container", { yPercent: 0, ease: "none" });
                ScrollTrigger.create({
                    trigger: ".main-content",
                    start: "bottom bottom",
                    end: "+=50%",
                    animation: uncover,
                    scrub: true,
                });
            }
        }
    };

    // Dom Ready
    $(function () {
        animation_text();
        scrolling_effect();
        scrollTransform();
        scrollBanners();
        animationFooter();
    });
})(jQuery);
